"""上下文压缩：会话超过 token 阈值时让 LLM 生成摘要替换旧消息。

设计要点（调研自 nanobot / OpenClaw）：
- 只压缩最旧的切片，最近 N 条原样保留（nanobot 默认 8 条）；
- 切分点保护工具调用对：assistant 的 tool_calls 与其 tool 结果不可切断，
  否则 OpenAI 兼容端点会直接报错（OpenClaw 的 pairing 保护）；
- 摘要失败兜底：硬截断但完整历史仍留在 SQLite（nanobot raw_archive 思路），
  数据不丢；
- 摘要消息本身入库存档，重开会话后依然生效。
"""

from __future__ import annotations

import logging

from minispark.config import MemoryConfig
from minispark.core.session import Session
from minispark.providers.base import Message, Provider

logger = logging.getLogger(__name__)

SUMMARY_MARKER = "[此前对话摘要]"
_TRUNCATED_NOTE = "[注：更早的对话因上下文过长已截断，完整历史已归档]"

_SUMMARY_PROMPT = """你是对话摘要器。把下面的对话历史压缩成摘要，供后续对话作为背景。
要求：
1. 保留关键事实、用户偏好、已做出的决定、未完成的事项；
2. 保留重要的文件路径、命令与标识符；
3. 分点列出，不超过 {max_tokens} token；
4. 不要寒暄，直接输出摘要。"""


def _build_summary_prompt(max_tokens: int) -> str:
    return _SUMMARY_PROMPT.format(max_tokens=max_tokens)


def estimate_tokens(messages: list[Message]) -> int:
    """粗略估算 token 数：CJK 字符按 1 token，其余按 4 字符 ≈ 1 token。

    中文 1 字 ≈ 1 token（GPT/DeepSeek 系 tokenizer 经验值），
    英文 1 token ≈ 4 字符；混合文本分段计数比统一 /4 准得多。
    """
    total = 0
    for m in messages:
        text = str(m.get("content") or "")
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        total += cjk + (len(text) - cjk) // 4
    return total


def find_safe_split(messages: list[Message], keep_recent: int) -> int:
    """返回保留尾部的起始下标。

    尾部不能以 tool 消息开头——tool 结果必须与其 assistant tool_calls 成对，
    从 tool 开头会把调用对切断，端点会报 400。
    """
    i = max(0, len(messages) - keep_recent)
    while i < len(messages) and messages[i].get("role") == "tool":
        i += 1
    return i


async def _summarize(old: list[Message], provider: Provider, max_tokens: int = 1000) -> str | None:
    lines = []
    for m in old:
        content = str(m.get("content") or "")
        if len(content) > 500:
            content = content[:500] + "…"
        lines.append(f"{m.get('role')}: {content}")
    try:
        reply = await provider.chat(
            [
                {"role": "system", "content": _build_summary_prompt(max_tokens)},
                {"role": "user", "content": "\n".join(lines)},
            ]
        )
    except Exception:
        logger.warning("上下文压缩：摘要请求失败，使用硬截断兜底", exc_info=True)
        return None
    return reply.content.strip() or None


async def maybe_compact(
    session: Session,
    provider: Provider,
    config: MemoryConfig,
    force: bool = False,
) -> bool:
    """会话过长时压缩旧消息。返回是否发生了压缩。

    :param force: 无视阈值强制压缩（用于 provider 报上下文溢出后的重试）。
    """
    messages = session.messages
    if not force and estimate_tokens(messages) <= config.compact_token_threshold:
        return False

    split = find_safe_split(messages, config.keep_recent_messages)
    if split <= 0:
        return False  # 没有可压缩的旧切片

    old, tail = messages[:split], messages[split:]
    summary = await _summarize(old, provider, max_tokens=config.summary_max_tokens)
    summary_msg: Message = {
        "role": "user",
        "content": f"{SUMMARY_MARKER}\n{summary}" if summary else _TRUNCATED_NOTE,
    }
    session.messages = [summary_msg, *tail]
    session.archive_prefix(summary_msg)
    logger.info(
        "上下文压缩：%d 条旧消息 -> %s，保留最近 %d 条",
        len(old),
        "摘要" if summary else "硬截断",
        len(tail),
    )
    return True