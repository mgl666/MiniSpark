"""记忆工具：memory_save / memory_search。

主动式持久化（借鉴 Hermes）：system prompt 指引模型在发现值得记住的
用户偏好/事实/约定时主动调用 memory_save，而非被动记录。
"""

from __future__ import annotations

from datetime import datetime

from minispark.memory.store import MemoryStore
from minispark.tools.base import FunctionTool


def create_memory_tools(store: MemoryStore) -> list[FunctionTool]:
    """按存储实例创建记忆工具组。"""

    def memory_save(content: str, tags: str = "") -> str:
        """保存一条长期记忆（用户偏好、重要事实、项目约定等）。

        :param content: 要记住的内容，一句话原子事实
        :param tags: 可选标签，逗号分隔
        """
        memory_id = store.save_memory(content.strip(), tags.strip())
        if memory_id is None:
            return "该内容已存在于记忆中，未重复保存。"
        return f"已记住（#{memory_id}）"

    def memory_search(query: str, limit: int = 5) -> str:
        """检索长期记忆，回答涉及用户过去提到的信息时先查一下。

        :param query: 检索关键词（多个词用空格分隔）
        :param limit: 最多返回条数
        """
        hits = store.search_memories(query, limit=limit)
        if not hits:
            return "没有找到相关记忆。"
        lines = []
        for h in hits:
            day = datetime.fromtimestamp(h["created_at"]).strftime("%Y-%m-%d")
            tag = f" [{h['tags']}]" if h["tags"] else ""
            lines.append(f"- (#{h['id']} {day}){tag} {h['content']}")
        return "\n".join(lines)

    def memory_update(old_content: str, new_content: str) -> str:
        """更新一条已有记忆。用户偏好改变时必须用它修改旧记忆，不要新增矛盾条目。

        :param old_content: 原记忆中的独特片段，用于定位（如"喜欢猫"）
        :param new_content: 替换后的完整记忆内容
        """
        hits = store.find_memories(old_content.strip())
        if not hits:
            return "没有找到匹配的记忆；如果是新信息，请用 memory_save 保存。"
        if len(hits) > 1:
            listing = "；".join(f"#{h['id']} {h['content']}" for h in hits)
            return f"匹配到多条记忆，请给出更精确的片段：{listing}"
        store.update_memory(hits[0]["id"], new_content.strip())
        return f"已更新记忆（#{hits[0]['id']}）"

    def memory_forget(query: str) -> str:
        """删除一条长期记忆，用户明确要求"忘掉…"时使用。

        :param query: 要删除的记忆中的独特片段
        """
        hits = store.find_memories(query.strip())
        if not hits:
            return "没有找到匹配的记忆。"
        if len(hits) > 1:
            listing = "；".join(f"#{h['id']} {h['content']}" for h in hits)
            return f"匹配到多条记忆，请给出更精确的片段：{listing}"
        store.delete_memory(hits[0]["id"])
        return f"已删除记忆（#{hits[0]['id']}）"

    return [
        FunctionTool(memory_save),
        FunctionTool(memory_search),
        FunctionTool(memory_update),
        FunctionTool(memory_forget),
    ]