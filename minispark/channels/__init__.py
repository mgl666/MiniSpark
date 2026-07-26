"""通道层：Channel 抽象与各平台适配器（CLI / QQ / 微信 / Email）。"""

from minispark.channels.email import EmailChannel
from minispark.channels.qq import QQBotChannel

__all__ = ["EmailChannel", "QQBotChannel"]