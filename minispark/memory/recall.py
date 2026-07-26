"""记忆检索：每轮对话开始时取 Top-K 相关记忆注入上下文。

v1 用 FTS5 关键词检索；向量检索接口预留，v2 可选装。
"""

from __future__ import annotations

from minispark.memory.store import MemoryStore


def recall_relevant(store: MemoryStore, query: str, top_k: int = 5) -> list[str]:
    """按用户输入检索相关记忆，返回待注入 system prompt 的文本列表。"""
    hits = store.search_memories(query, limit=top_k)
    return [h["content"] for h in hits]
