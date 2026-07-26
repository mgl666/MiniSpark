"""模型接入层：Provider 抽象 + OpenAI 兼容通用接口。"""

from minispark.providers.base import Message, Provider, ProviderReply, ToolCall
from minispark.providers.openai_compat import OpenAICompatProvider

__all__ = ["Message", "Provider", "ProviderReply", "ToolCall", "OpenAICompatProvider"]
