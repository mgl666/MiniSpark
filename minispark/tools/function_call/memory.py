"""Memory tools: memory_save / memory_search.

Proactive persistence (inspired by Hermes): the system prompt instructs the model to
proactively call memory_save when it discovers user preferences/facts/agreements worth remembering,
rather than passive recording.
"""

from __future__ import annotations

from datetime import datetime

from minispark.memory.store import MemoryStore
from minispark.tools.base import FunctionTool


def create_memory_tools(store: MemoryStore) -> list[FunctionTool]:
    """Create memory tool group based on the storage instance."""

    def memory_save(content: str, tags: str = "") -> str:
        """Save a long-term memory entry (user preferences, important facts, project conventions, etc.).

        :param content: Content to remember, a single atomic fact
        :param tags: Optional tags, comma-separated
        """
        memory_id = store.save_memory(content.strip(), tags.strip())
        if memory_id is None:
            return "This content already exists in memory, not saved again."
        return f"Remembered (#{memory_id})"

    def memory_search(query: str, limit: int = 5) -> str:
        """Search long-term memories. Check this first when answering questions involving past user information.

        :param query: Search keywords (space-separated for multiple words)
        :param limit: Maximum number of results
        """
        hits = store.search_memories(query, limit=limit)
        if not hits:
            return "No relevant memories found."
        lines = []
        for h in hits:
            day = datetime.fromtimestamp(h["created_at"]).strftime("%Y-%m-%d")
            tag = f" [{h['tags']}]" if h["tags"] else ""
            lines.append(f"- (#{h['id']} {day}){tag} {h['content']}")
        return "\n".join(lines)

    def memory_update(old_content: str, new_content: str) -> str:
        """Update an existing memory. When user preferences change, use this to modify the old memory instead of creating conflicting entries.

        :param old_content: A unique fragment from the original memory to locate it (e.g. "likes cats")
        :param new_content: The complete replacement memory content
        """
        hits = store.find_memories(old_content.strip())
        if not hits:
            return "No matching memory found; if this is new information, use memory_save to save it."
        if len(hits) > 1:
            listing = "; ".join(f"#{h['id']} {h['content']}" for h in hits)
            return f"Multiple memories matched, please provide a more precise fragment: {listing}"
        store.update_memory(hits[0]["id"], new_content.strip())
        return f"Memory updated (#{hits[0]['id']})"

    def memory_forget(query: str) -> str:
        """Delete a long-term memory. Use when the user explicitly asks to 'forget...'

        :param query: A unique fragment from the memory to delete
        """
        hits = store.find_memories(query.strip())
        if not hits:
            return "No matching memory found."
        if len(hits) > 1:
            listing = "; ".join(f"#{h['id']} {h['content']}" for h in hits)
            return f"Multiple memories matched, please provide a more precise fragment: {listing}"
        store.delete_memory(hits[0]["id"])
        return f"Memory deleted (#{hits[0]['id']})"

    return [
        FunctionTool(memory_save),
        FunctionTool(memory_search),
        FunctionTool(memory_update),
        FunctionTool(memory_forget),
    ]