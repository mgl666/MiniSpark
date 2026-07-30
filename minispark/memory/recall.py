"""Memory retrieval: fetch Top-K relevant memories at the start of each conversation turn and inject into context.

v1 uses FTS5 keyword search; vector retrieval interface is reserved for optional v2 upgrade.
"""

from __future__ import annotations

from minispark.memory.store import MemoryStore


def recall_relevant(store: MemoryStore, query: str, top_k: int = 5) -> list[str]:
    """Search for relevant memories based on user input, return text list for system prompt injection."""
    hits = store.search_memories(query, limit=top_k)
    return [h["content"] for h in hits]