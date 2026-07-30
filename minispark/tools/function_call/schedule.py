"""Scheduled task tools: schedule_task / list_tasks / cancel_task.

Allows the Agent to create, view, and cancel scheduled tasks during conversations.
"""

from __future__ import annotations

import time
import uuid

from minispark.scheduler import ScheduledTask, Scheduler
from minispark.tools.base import FunctionTool


def create_schedule_tools(scheduler: Scheduler) -> list[FunctionTool]:
    """Create scheduled task tool group based on the scheduler instance."""

    def schedule_task(name: str, run_at: str = "", cron_expression: str = "", prompt: str = "", channel: str = "", openid: str = "", group_openid: str = "", msg_type: str = "") -> str:
        """[IMPORTANT] Create a one-time or recurring scheduled task.

        When the user asks to 'do something later, in a few minutes, tomorrow, or at a specific time/interval',
        call this tool instead of executing immediately. Put the full request to execute at the due time into prompt.

        :param name: Short task name
        :param run_at: One-time execution time, ISO format
        :param cron_expression: Cron expression for recurring tasks
        :param prompt: Full request to execute at the due time
        :param channel: Optional result push channel
        :param openid: Internal use, do not set
        :param group_openid: Internal use, do not set
        :param msg_type: Internal use, do not set
        """
        task = ScheduledTask(
            id=uuid.uuid4().hex[:12],
            name=name.strip(),
            cron_expression=cron_expression.strip(),
            run_at=run_at.strip(),
            prompt=prompt.strip(),
            channel=channel.strip(),
            openid=openid.strip(),
            group_openid=group_openid.strip(),
            msg_type=msg_type.strip(),
            created_at=time.time(),
        )
        scheduler.add(task)
        if run_at.strip():
            return f"Scheduled task '{task.name}' created (ID: {task.id}), will execute at {run_at.strip()}"
        return f"Scheduled task '{task.name}' created (ID: {task.id}), cron: {task.cron_expression}"

    def list_tasks() -> str:
        """List all created scheduled tasks."""
        tasks = scheduler.list()
        if not tasks:
            return "No scheduled tasks at the moment."
        lines = []
        for t in tasks:
            status = "enabled" if t.enabled else "disabled"
            ch = f" -> {t.channel}" if t.channel else ""
            if t.run_at:
                schedule = f"at {t.run_at} (one-time)"
            elif t.cron_expression:
                schedule = f"cron: {t.cron_expression}"
            else:
                schedule = "invalid"
            lines.append(f"- [{status}] {t.name} (ID: {t.id}) {schedule}{ch}")
        return "\n".join(lines)

    def cancel_task(task_id: str) -> str:
        """Cancel a scheduled task.

        :param task_id: Task ID (returned during creation or from list_tasks)
        """
        if scheduler.remove(task_id.strip()):
            return f"Scheduled task cancelled (ID: {task_id})"
        return f"Scheduled task not found (ID: {task_id})"

    return [
        FunctionTool(schedule_task),
        FunctionTool(list_tasks),
        FunctionTool(cancel_task),
    ]