"""Provider 抽象层。

Agent Core 与模型供应商之间的唯一接口：chat(messages, tools) -> ProviderReply。
保留这层薄抽象，为将来接入非 OpenAI 兼容协议（如 Anthropic 原生 API）留插槽。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# 消息统一使用 OpenAI chat.completions 的 dict 格式，
# 会话历史可直接透传给任何兼容端点。
Message = dict[str, Any]


@dataclass
class ToolCall:
    """模型返回的一次工具调用请求。"""

    id: str
    """工具调用 ID，回填 tool 消息时用于对应。"""

    name: str
    """工具名。"""

    arguments: dict[str, Any]
    """解析后的调用参数。"""

    raw_arguments: str = "{}"
    """原始 JSON 字符串，回填 assistant 消息时原样使用，避免二次序列化失真。"""


@dataclass
class ProviderReply:
    """模型一轮回复的结果。"""

    content: str = ""
    """文本回复（可能为空，如纯工具调用轮）。"""

    tool_calls: list[ToolCall] = field(default_factory=list)
    """本轮请求执行的工具调用列表。"""


class Provider(ABC):
    """模型供应商抽象。所有实现对 Agent Core 暴露同一个 chat 接口。"""

    @abstractmethod
    async def chat(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> ProviderReply:
        """请求模型生成下一轮回复。

        :param messages: OpenAI 格式的完整对话历史（含 system）。
        :param tools: OpenAI tools 格式的工具 schema 列表，None 表示不提供工具。
        :return: 模型的文本回复与/或工具调用请求。
        """
