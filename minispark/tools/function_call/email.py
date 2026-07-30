"""Email sending tool: send_email.

Allows the Agent to send emails directly during conversations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from minispark.tools.base import FunctionTool

if TYPE_CHECKING:
    from minispark.channels.email import EmailChannel


def create_email_tools(email_channel: EmailChannel, default_to: str = "") -> list[FunctionTool]:
    """Create email tools based on the email channel instance."""

    def send_email(to: str, subject: str, body: str) -> str:
        """Send an email to the specified address. When no recipient is specified, use the default.

        :param to: Recipient email address, multiple addresses separated by commas. Use default when not specified
        :param subject: Email subject
        :param body: Email body (plain text)
        """
        if not to and default_to:
            to = default_to
        oks = []
        for addr in (a.strip() for a in to.split(",") if a.strip()):
            if email_channel.send(addr, subject, body):
                oks.append(addr)
        if oks:
            return f"Email sent to {', '.join(oks)}"
        return f"Email send failed, please check email configuration"

    return [FunctionTool(send_email)]