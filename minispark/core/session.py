"""会话对象：消息历史、状态与 SQLite 持久化。

M2 起会话落盘：同名 session_id 重开自动恢复历史（关掉再打开也记得）。
消息以 OpenAI chat.completions 的 dict 格式保存，可原样透传兼容端点。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from minispark.providers.base import Message

if TYPE_CHECKING:
    from minispark.memory.store import MemoryStore


@dataclass
class Session:
    """一次持续对话的上下文容器。会话隔离维度为 ``channel:chat_id``（M3）。"""

    session_id: str
    messages: list[Message] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    _store: MemoryStore | None = field(default=None, repr=False)
    _persisted: int = field(default=0, repr=False)
    """已写入 SQLite 的消息条数（增量持久化游标）。"""

    @classmethod
    def new(cls, session_id: str | None = None, store: MemoryStore | None = None) -> Session:
        """创建会话；给定 store 时自动恢复同名会话的未压缩历史。"""
        sid = session_id or uuid.uuid4().hex[:12]
        messages = store.load_messages(sid) if store else []
        return cls(session_id=sid, messages=messages, _store=store, _persisted=len(messages))

    def persist(self) -> None:
        """把新增消息增量写入 SQLite（无 store 时为纯内存会话）。"""
        if not self._store:
            return
        for message in self.messages[self._persisted :]:
            self._store.add_message(self.session_id, message)
        self._persisted = len(self.messages)

    def archive_prefix(self, summary_msg: Message) -> None:
        """上下文压缩后调用：把压缩后的新历史（摘要 + 尾部）整段重写入库。

        调用前 ``self.messages`` 应已被替换为 ``[summary_msg, *tail]``。
        整段重写是为了让重载后摘要排在最前（行 id 即顺序）。
        """
        if self._store:
            self._store.mark_compacted(self.session_id, count=10**9)  # 全部归档
            for message in self.messages:
                self._store.add_message(self.session_id, message)
        self._persisted = len(self.messages)
