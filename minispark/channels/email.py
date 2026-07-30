"""Gmail email channel.

Send emails via SMTP + App Password, pure Python built-in, zero external dependencies.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


class EmailChannel:
    """Gmail SMTP email sending channel."""

    def __init__(self, sender: str, password: str, to: str = "") -> None:
        self._sender = sender
        self._password = password
        self._to = to

    @property
    def is_ready(self) -> bool:
        return True

    def verify(self) -> str:
        return "SMTP mode, no authorization required, ready"

    def send(self, to: str, subject: str, body: str) -> bool:
        try:
            msg = MIMEText(body, "plain", "utf-8")
            msg["From"] = self._sender
            msg["To"] = to
            msg["Subject"] = subject

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(self._sender, self._password)
                server.sendmail(self._sender, [to], msg.as_string())
            logger.info("Email sent -> %s", to)
            return True
        except Exception:
            logger.exception("Email send failed -> %s", to)
            return False