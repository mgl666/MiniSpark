"""OpenAI 兼容通用接口。

一份代码覆盖所有 OpenAI 兼容端点：OpenAI / DeepSeek / Kimi / 通义 / 智谱 /
vLLM / Ollama 等。切换模型 = 改配置文件，不改代码。
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
    """基于 openai 官方 SDK 的通用 Provider，指向任意 base_url。"""

    def __init__(self, config: ProviderConfig) -> None:
        self._model = config.model
        # 本地端点（如 Ollama）通常不校验 key，用占位符避免 SDK 报错
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
        """从 API 获取可用模型列表（结果缓存，首次调用后不再请求）。"""
        if self._cached_models is not None:
            return self._cached_models
        try:
            resp = await self._client.models.list()
            self._cached_models = sorted(
                [m.id for m in resp.data if m.id and not m.id.startswith("ft:")]
            )
        except Exception:
            logger.warning("获取模型列表失败，返回空列表", exc_info=True)
            self._cached_models = []
        return self._cached_models

    async def chat(
        self, messages: list[Message], tools: list[dict[str, Any]] | None = None
    ) -> ProviderReply:
        kwargs: dict[str, Any] = {"model": self._model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        logger.debug(
            "请求模型 %s（%d 条消息，%d 个工具）", self._model, len(messages), len(tools or [])
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
                    "工具 %s 参数 JSON 解析失败，按空调用处理: %s", tc.function.name, raw
                )
                arguments = {}
            tool_calls.append(
                ToolCall(id=tc.id, name=tc.function.name, arguments=arguments, raw_arguments=raw)
            )
        return ProviderReply(content=message.content or "", tool_calls=tool_calls)