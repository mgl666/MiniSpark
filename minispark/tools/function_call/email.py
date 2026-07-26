"""邮件发送工具：send_email。

让 Agent 在对话中直接发送邮件。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from minispark.tools.base import FunctionTool

if TYPE_CHECKING:
    from minispark.channels.email import EmailChannel


def create_email_tools(email_channel: EmailChannel, default_to: str = "") -> list[FunctionTool]:
    """按邮件通道实例创建邮件工具。"""

    def send_email(to: str, subject: str, body: str) -> str:
        """发送邮件到指定邮箱。用户未指定收件人时，to 填默认收件人。

        :param to: 收件人邮箱地址，多个地址用英文逗号分隔。用户未指定时填默认收件人
        :param subject: 邮件主题
        :param body: 邮件正文（纯文本）
        """
        if not to and default_to:
            to = default_to
        oks = []
        for addr in (a.strip() for a in to.split(",") if a.strip()):
            if email_channel.send(addr, subject, body):
                oks.append(addr)
        if oks:
            return f"邮件已发送到 {', '.join(oks)}"
        return f"邮件发送失败，请检查邮箱配置"

    return [FunctionTool(send_email)]