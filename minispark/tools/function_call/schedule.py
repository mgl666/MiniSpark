"""定时任务工具：schedule_task / list_tasks / cancel_task。

让 Agent 在对话中自助创建、查看和取消定时任务。
"""

from __future__ import annotations

import time
import uuid

from minispark.scheduler import ScheduledTask, Scheduler
from minispark.tools.base import FunctionTool


def create_schedule_tools(scheduler: Scheduler) -> list[FunctionTool]:
    """按调度器实例创建定时任务工具组。"""

    def schedule_task(name: str, run_at: str = "", cron_expression: str = "", prompt: str = "", channel: str = "") -> str:
        """【关键】创建一次性或周期定时任务。

        用户要求“稍后、几分钟后、明天等指定时间或周期执行”时，应调用本工具，
        不要立即执行。将到期后需要执行的完整请求写入 prompt。

        :param name: 简短任务名称
        :param run_at: 一次性执行时间，ISO 格式
        :param cron_expression: 周期任务的 cron 表达式
        :param prompt: 到期后执行的完整请求
        :param channel: 可选的结果推送通道
        """
        task = ScheduledTask(
            id=uuid.uuid4().hex[:12],
            name=name.strip(),
            cron_expression=cron_expression.strip(),
            run_at=run_at.strip(),
            prompt=prompt.strip(),
            channel=channel.strip(),
            created_at=time.time(),
        )
        scheduler.add(task)
        if run_at.strip():
            return f"已创建定时任务「{task.name}」(ID: {task.id})，将于 {run_at.strip()} 执行"
        return f"已创建定时任务「{task.name}」(ID: {task.id})，cron: {task.cron_expression}"

    def list_tasks() -> str:
        """列出所有已创建的定时任务。"""
        tasks = scheduler.list()
        if not tasks:
            return "当前没有定时任务。"
        lines = []
        for t in tasks:
            status = "启用" if t.enabled else "停用"
            ch = f" → {t.channel}" if t.channel else ""
            if t.run_at:
                schedule = f"定时 {t.run_at}（一次性）"
            elif t.cron_expression:
                schedule = f"cron: {t.cron_expression}"
            else:
                schedule = "无效"
            lines.append(f"- [{status}] {t.name} (ID: {t.id}) {schedule}{ch}")
        return "\n".join(lines)

    def cancel_task(task_id: str) -> str:
        """取消一个定时任务。

        :param task_id: 任务 ID（创建时返回或从 list_tasks 获取）
        """
        if scheduler.remove(task_id.strip()):
            return f"已取消定时任务 (ID: {task_id})"
        return f"未找到定时任务 (ID: {task_id})"

    return [
        FunctionTool(schedule_task),
        FunctionTool(list_tasks),
        FunctionTool(cancel_task),
    ]