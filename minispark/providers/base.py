"""Provider abstraction layer.

The sole interface between Agent Core and model providers: chat(messages, tools) -> ProviderReply.
This thin abstraction is kept for future non-OpenAI-compatible protocols (e.g. Anthropic native API).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# Messages use OpenAI chat.completions dict format uniformly,
# session history can be passed directly to any compatible endpoint.
Message = dict[str, Any]


@dataclass
class ToolCall:
    """A tool call request returned by the model."""

    id: str
    """Tool call ID, used to match tool result messages when backfilling."""

    name: str
    """Tool name."""

    arguments: dict[str, Any]
    """Parsed call arguments."""

    raw_arguments: str = "{}"
    """Original JSON string, used as-is when backfilling assistant messages to avoid double serialization distortion."""


@dataclass
class ProviderReply:
    """Result of one model response round."""

    content: str = ""
    """Text reply (may be empty, e.g. pure tool call round)."""

    tool_calls: list[ToolCall] = field(default_factory=list)
    """List of tool calls to execute this round."""


class Provider(ABC):
    """Model provider abstraction. All implementations expose the same chat interface to Agent Core."""

    @abstractmethod
    async def chat(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> ProviderReply:
        """Request the model to generate the next round of reply.

        :param messages: Full conversation history in OpenAI format (including system).
        :param tools: Tool schema list in OpenAI tools format, None means no tools provided.
        :return: Model's text reply and/or tool call requests.
        """