"""OpenAI-compatible universal interface.

One codebase covers all OpenAI-compatible endpoints: OpenAI / DeepSeek / Kimi / Tongyi / Zhipu /
vLLM / Ollama, etc. Switching models = changing config file, no code changes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from minispark.config import ProviderConfig
from minispark.providers.base import Message, Provider, ProviderReply, ToolCall

logger = logging.getLogger(__name__)


class OpenAICompatProvider(Provider):
    """Universal Provider based on the official openai SDK, pointing to any base_url."""

    def __init__(self, config: ProviderConfig) -> None:
        self._model = config.model
        # Local endpoints (e.g. Ollama) typically don't validate keys, use placeholder to avoid SDK errors
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key or "EMPTY",
        )
        self._cached_models: list[str] | None = None

    @property
    def model(self) -> str:
        return self._model

    def switch_model(self, new_model: str) -> str:
        self._model = new_model
        return self._model

    async def fetch_models(self) -> list[str]:
        """Fetch available model list from the API (cached, only requested once)."""
        if self._cached_models is not None:
            return self._cached_models
        try:
            resp = await self._client.models.list()
            self._cached_models = sorted(
                [m.id for m in resp.data if m.id and not m.id.startswith("ft:")]
            )
        except Exception:
            logger.warning("Failed to fetch model list, returning empty list", exc_info=True)
            self._cached_models = []
        return self._cached_models

    async def chat(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> ProviderReply:
        kwargs: dict[str, Any] = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        logger.debug(
            "Requesting model %s (%d messages, %d tools)", self._model, len(messages), len(tools or [])
        )
        resp = await self._client.chat.completions.create(**kwargs)
        message = resp.choices[0].message

        tool_calls: list[ToolCall] = []
        for tc in message.tool_calls or []:
            raw = tc.function.arguments or "{}"
            try:
                arguments = json.loads(raw)
                if not isinstance(arguments, dict):
                    arguments = {}
            except json.JSONDecodeError:
                logger.warning(
                    "Tool %s argument JSON parsing failed, treating as empty call: %s", tc.function.name, raw
                )
                arguments = {}
            tool_calls.append(
                ToolCall(id=tc.id, name=tc.function.name, arguments=arguments, raw_arguments=raw)
            )
        return ProviderReply(content=message.content or "", tool_calls=tool_calls)