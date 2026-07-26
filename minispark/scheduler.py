"""定时任务调度器：cron 表达式 → 触发 Agent 执行 prompt。

基于 APScheduler，任务定义持久化到 SQLite，重启不丢。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Any

from apscheduler.job import Job as APSJob
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from datetime import datetime

from minispark.memory.store import sqlite3

logger = logging.getLogger(__name__)

logging.getLogger("apscheduler").setLevel(logging.WARNING)

_SCHEDULE_SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cron_expression TEXT NOT NULL DEFAULT '',
    delay_seconds INTEGER NOT NULL DEFAULT 0,
    run_at TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
"""


@dataclass
class ScheduledTask:
    """一个定时任务的定义。

    两种触发模式：
    1. ``run_at`` 非空 → 在指定 ISO 时间点执行一次（如 "2025-07-15T08:00:00"）
    2. ``cron_expression`` 非空 → 按 cron 周期重复执行

    可组合：``run_at`` 指定首次执行，之后按 cron 周期。
    """

    id: str
    name: str
    cron_expression: str = ""
    run_at: str = ""
    prompt: str = ""
    channel: str = ""
    enabled: bool = True
    created_at: float = 0.0


class SchedulerStore:
    """定时任务持久化（SQLite）。"""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEDULE_SCHEMA)
        self._conn.commit()

    def save(self, task: ScheduledTask) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO scheduled_tasks (id, name, cron_expression, run_at, prompt, channel, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task.id, task.name, task.cron_expression, task.run_at, task.prompt, task.channel, int(task.enabled), task.created_at),
        )
        self._conn.commit()

    def load_all(self) -> list[ScheduledTask]:
        rows = self._conn.execute("SELECT * FROM scheduled_tasks ORDER BY created_at").fetchall()
        return [_row_to_task(r) for r in rows]

    def delete(self, task_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def get(self, task_id: str) -> ScheduledTask | None:
        row = self._conn.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_task(row) if row else None


def _row_to_task(row: sqlite3.Row) -> ScheduledTask:
    return ScheduledTask(
        id=row["id"],
        name=row["name"],
        cron_expression=row["cron_expression"],
        run_at=row["run_at"] if "run_at" in row.keys() else "",
        prompt=row["prompt"],
        channel=row["channel"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
    )


class Scheduler:
    """定时任务调度器。

    核心职责：管理 cron 任务，到期时以任务 prompt 为输入跑一次 Agent，
    结果通过 ``_on_result`` 回调外传（由 Gateway 绑定通道推送）。
    """

    def __init__(
        self,
        store: SchedulerStore,
        on_result: Callable[[ScheduledTask, str], Any] | None = None,
    ) -> None:
        self._store = store
        self._on_result = on_result
        self._aps = AsyncIOScheduler()
        self._agent_fn: Callable[[str], Any] | None = None

    def bind_agent(self, agent_fn: Callable[[str], Any]) -> None:
        """绑定 Agent 执行函数。``agent_fn(prompt)`` 将被调度器调用。"""
        self._agent_fn = agent_fn

    def start(self) -> None:
        """启动调度器，恢复持久化任务。过期的一次性任务自动清理。"""
        now = datetime.now()
        for task in self._store.load_all():
            if task.run_at:
                try:
                    run_time = datetime.fromisoformat(task.run_at)
                except ValueError:
                    self._store.delete(task.id)
                    continue
                if run_time < now:
                    self._store.delete(task.id)
                    logger.debug("清理过期任务: %s (%s)", task.name, task.id)
                    continue
            if task.enabled:
                self._add_aps_job(task)
        self._aps.start()
        logger.debug("调度器已启动，当前 %d 个活跃任务", len(self._aps.get_jobs()))

    def stop(self) -> None:
        self._aps.shutdown(wait=False)
        logger.info("调度器已停止")

    @property
    def running(self) -> bool:
        return self._aps.running

    def add(self, task: ScheduledTask) -> None:
        """添加一个定时任务。若调度器已运行且 run_at 已过期则拒绝。"""
        if task.run_at and self.running:
            try:
                run_time = datetime.fromisoformat(task.run_at)
            except ValueError:
                raise ValueError(f"无效的时间格式: {task.run_at}")
            if run_time < datetime.now():
                raise ValueError(f"执行时间已过期: {task.run_at}（当前 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）")
        task.created_at = task.created_at or __import__("time").time()
        self._store.save(task)
        if task.enabled:
            self._add_aps_job(task)
        logger.debug("已添加定时任务: %s (%s)", task.name, task.id)

    def remove(self, task_id: str) -> bool:
        """删除一个定时任务。"""
        try:
            self._aps.remove_job(task_id)
        except Exception:
            pass
        ok = self._store.delete(task_id)
        if ok:
            logger.debug("已删除定时任务: %s", task_id)
        return ok

    def list(self) -> list[ScheduledTask]:
        """列出所有定时任务。"""
        return self._store.load_all()

    def _add_aps_job(self, task: ScheduledTask) -> None:
        if task.run_at:
            try:
                run_time = datetime.fromisoformat(task.run_at)
            except ValueError:
                logger.warning("无效 run_at 时间格式: %s (任务 %s)", task.run_at, task.id)
                return
            trigger: DateTrigger | CronTrigger = DateTrigger(run_date=run_time)
        elif task.cron_expression:
            try:
                trigger = CronTrigger.from_crontab(task.cron_expression)
            except Exception:
                logger.warning("无效 cron 表达式: %s (任务 %s)", task.cron_expression, task.id)
                return
        else:
            logger.warning("任务 %s 既无 run_at 也无 cron 表达式，跳过", task.id)
            return

        self._aps.add_job(
            self._execute,
            trigger=trigger,
            id=task.id,
            name=task.name,
            kwargs={"task": task},
            replace_existing=True,
        )

    async def _execute(self, task: ScheduledTask) -> None:
        """执行一次定时任务：跑 Agent → 回调结果。一次性任务执行完自动删除。"""
        logger.debug("定时任务触发: %s", task.name)
        if self._agent_fn is None:
            logger.error("调度器未绑定 Agent 函数，跳过任务 %s", task.name)
            return

        try:
            result = self._agent_fn(task.prompt)
            if __import__("asyncio").iscoroutine(result):
                result = await result
            result_str = str(result)
        except Exception:
            logger.exception("定时任务执行失败: %s", task.name)
            result_str = f"定时任务执行失败: {task.name}"

        if self._on_result:
            try:
                cb = self._on_result(task, result_str)
                if __import__("asyncio").iscoroutine(cb):
                    await cb
            except Exception:
                logger.exception("定时任务结果回调失败: %s", task.name)

        if task.run_at:
            self.remove(task.id)