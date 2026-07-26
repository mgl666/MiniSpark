"""Agent 主循环 —— 本项目的心脏。

一轮循环只做两类外呼：问模型"接下来做什么"（Provider），
或"执行模型要求的工具"（ToolRegistry）。两者都是单向服务，互不调用。

链路：接收消息 → 组装上下文（含记忆）→ 请求 LLM → 若返回工具调用则并行执行
并回填 → 循环，直到 LLM 给出最终回复或达到最大轮数熔断。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from minispark.config import Config, load_config
from minispark.core.compaction import maybe_compact
from minispark.core.context import build_system_prompt
from minispark.core.session import Session
from minispark.memory.recall import recall_relevant
from minispark.memory.store import MemoryStore
from minispark.providers.base import Message, Provider, ProviderReply
from minispark.providers.openai_compat import OpenAICompatProvider
from minispark.scheduler import Scheduler, SchedulerStore
from minispark.tools.skills.loader import Skill, discover_skills
from minispark.tools.function_call.fs import create_fs_tools
from minispark.tools.function_call.memory import create_memory_tools
from minispark.tools.function_call.shell import ConfirmFn, create_shell_tool
from minispark.tools.skill import create_skill_tool
from minispark.tools.function_call.web import create_web_tools
from minispark.tools.function_call.schedule import create_schedule_tools
from minispark.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_DEFAULT_MAX_TURNS = 20

# provider 上下文溢出报错的常见特征（OpenClaw compact-and-retry 思路）
_OVERFLOW_HINTS = (
    "context length",
    "context window",
    "maximum context",
    "too many tokens",
    "request_too_large",
    "input is too long",
    "max_tokens",
    "token limit",
)


def _is_context_overflow(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(hint in text for hint in _OVERFLOW_HINTS)


def build_default_registry(
    config: Config,
    confirm: ConfirmFn | None = None,
    store: MemoryStore | None = None,
    skills: dict[str, Skill] | None = None,
    scheduler: Scheduler | None = None,
) -> ToolRegistry:
    """创建注册表并装入全部内置工具。"""
    from minispark.scheduler import Scheduler, SchedulerStore

    if scheduler is None:
        scheduler = Scheduler(SchedulerStore(config.scheduler.resolved_db_path))

    registry = ToolRegistry(result_char_limit=config.agent.result_char_limit)
    for tool in create_fs_tools(config.tools):
        registry.register(tool)
    registry.register(create_shell_tool(config.tools, confirm=confirm))
    if store is not None:
        for tool in create_memory_tools(store):
            registry.register(tool)
    for tool in create_web_tools():
        registry.register(tool)
    for tool in create_schedule_tools(scheduler):
        registry.register(tool)
    if skills:
        registry.register(create_skill_tool(skills))
    return registry


class Agent:
    """MiniSpark Agent。可经 ``Agent.from_config`` 从配置文件一行构建。"""

    def __init__(
        self,
        config: Config,
        provider: Provider,
        registry: ToolRegistry,
        store: MemoryStore | None = None,
        skills: dict[str, Skill] | None = None,
        scheduler: Scheduler | None = None,
    ) -> None:
        self._config = config
        self._provider = provider
        self._registry = registry
        self._store = store
        self._skills = discover_skills() if skills is None else skills
        self._scheduler = scheduler

    @classmethod
    def from_config(
        cls, path: str | Path = "config.toml", confirm: ConfirmFn | None = None
    ) -> Agent:
        """从配置文件构建 Agent（库嵌入入口）。"""
        config = load_config(path)
        return cls.from_config_object(config, confirm=confirm)

    @classmethod
    def from_config_object(cls, config: Config, confirm: ConfirmFn | None = None) -> Agent:
        """从已加载的配置对象构建 Agent（记忆存储初始化失败时降级为无记忆模式）。"""
        provider = OpenAICompatProvider(config.provider)
        store: MemoryStore | None = None
        try:
            store = MemoryStore(config.memory.resolved_db_path)
        except Exception:
            logger.warning("记忆存储初始化失败，本次以无记忆模式运行", exc_info=True)
        skills = discover_skills()
        scheduler = Scheduler(SchedulerStore(config.scheduler.resolved_db_path))
        registry = build_default_registry(config, confirm=confirm, store=store, skills=skills, scheduler=scheduler)
        return cls(config, provider, registry, store=store, skills=skills, scheduler=scheduler)

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def scheduler(self) -> Scheduler | None:
        return self._scheduler

    @property
    def store(self) -> MemoryStore | None:
        return self._store

    @property
    def skills(self) -> dict[str, Skill]:
        return self._skills

    @property
    def model(self) -> str:
        return self._provider.model

    @property
    def model_list(self) -> list[str]:
        return self._config.provider.model_list

    async def list_models(self) -> list[str]:
        return await self._provider.fetch_models()

    def switch_model(self, new_model: str) -> str:
        self._config.provider.model = new_model
        return self._provider.switch_model(new_model)

    def _recall(self, query: str) -> list[str]:
        """检索与本轮输入相关的长期记忆（失败不阻断对话）。"""
        if self._store is None:
            return []
        try:
            return recall_relevant(self._store, query, self._config.memory.recall_top_k)
        except Exception:
            logger.warning("记忆检索失败，本轮不注入记忆", exc_info=True)
            return []

    async def compact(self, session: Session, *, force: bool = True) -> bool:
        """压缩会话上下文（供 /compact 命令与外部调用）。

        :param force: 无视 token 阈值强制压缩；False 时仅在超阈值时压缩。
        :return: 是否实际发生了压缩。
        """
        return await maybe_compact(session, self._provider, self._config.memory, force=force)

    async def run(self, message: str, session: Session | None = None) -> str:
        """处理一条用户消息，返回最终文本回复。

        :param message: 用户输入。
        :param session: 会话对象（携带历史）；None 表示单次无状态对话。
        """
        session = session or Session.new()
        session.messages.append({"role": "user", "content": message})
        await maybe_compact(session, self._provider, self._config.memory)

        # system prompt 每轮重新组装：注入相关记忆与技能目录，不写入会话历史
        system = build_system_prompt(
            self._config, memories=self._recall(message), skills=self._skills
        )
        messages: list[Message] = [{"role": "system", "content": system}, *session.messages]

        max_turns = self._config.agent.max_turns or _DEFAULT_MAX_TURNS
        try:
            for turn in range(1, max_turns + 1):
                logger.debug("Agent 第 %d/%d 轮", turn, max_turns)
                try:
                    reply = await self._provider.chat(messages, self._registry.schemas())
                except Exception as exc:
                    # 上下文溢出：压缩后重组消息重试一次（OpenClaw compact-and-retry）
                    if _is_context_overflow(exc) and await maybe_compact(
                        session, self._provider, self._config.memory, force=True
                    ):
                        logger.info("检测到上下文溢出，已压缩会话并重试")
                        messages = [{"role": "system", "content": system}, *session.messages]
                        continue
                    raise

                if not reply.tool_calls:
                    session.messages.append({"role": "assistant", "content": reply.content})
                    return reply.content

                assistant_msg = self._assistant_message(reply)
                session.messages.append(assistant_msg)
                messages.append(assistant_msg)

                # 一轮可能返回多个工具调用，并行执行
                results = await asyncio.gather(
                    *(self._registry.execute(tc.name, tc.arguments) for tc in reply.tool_calls)
                )
                for tc, result in zip(reply.tool_calls, results, strict=True):
                    logger.info("工具 %s -> %d 字符", tc.name, len(result))
                    tool_msg: Message = {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    }
                    session.messages.append(tool_msg)
                    messages.append(tool_msg)

            warning = (
                f"已达到最大工具调用轮数（{max_turns}），任务被熔断。"
                "请缩小任务范围，或在配置中调大 agent.max_turns。"
            )
            logger.warning(warning)
            session.messages.append({"role": "assistant", "content": warning})
            return warning
        finally:
            session.persist()  # 异常退出也尽量保住本轮历史

    @staticmethod
    def _assistant_message(reply: ProviderReply) -> Message:
        """把模型回复（含工具调用）组装成 OpenAI 格式的 assistant 消息。"""
        msg: Message = {"role": "assistant", "content": reply.content or None}
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": tc.raw_arguments or _dumps(tc.arguments),
                },
            }
            for tc in reply.tool_calls
        ]
        return msg


def _dumps(arguments: dict) -> str:
    return json.dumps(arguments, ensure_ascii=False)