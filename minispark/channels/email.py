"""Gmail 邮件通道。

通过 SMTP + 应用专用密码发送邮件，纯 Python 内置，无需任何外部依赖。
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class EmailChannel:
    """Gmail SMTP 邮件发送通道。"""

    def __init__(self, sender: str, password: str, to: str = "") -> None:
        self._sender = sender
        self._password = password
        self._to = to

    @property
    def is_ready(self) -> bool:
        return True

    def verify(self) -> str:
        return "SMTP 模式无需授权，已就绪"

    def send(self, to: str, subject: str, body: str) -> bool:
        try:
            msg = MIMEText(body, "plain", "utf-8")
            msg["From"] = self._sender
            msg["To"] = to
            msg["Subject"] = subject

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self._sender, self._password)
                server.sendmail(self._sender, [to], msg.as_string())
            logger.info("邮件已发送 -> %s", to)
            return True
        except Exception:
            logger.exception("邮件发送失败 -> %s", to)
            return False