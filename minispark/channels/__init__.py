"""Channel layer: Channel abstraction and platform adapters (CLI / QQ / WeChat / Email)."""

from minispark.channels.email import EmailChannel
from minispark.channels.qq import QQBotChannel

__all__ = ["EmailChannel", "QQBotChannel"]