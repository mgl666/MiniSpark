"""SQLite 存储：会话历史 + 长期记忆。

单文件数据库（默认包内 ``minispark/memory/minispark.db``），零外部服务依赖：

- ``messages`` 表：全部会话历史（压缩只打标记不删除，完整历史永不丢）；
- ``memories`` 表 + FTS5 全文索引：长期记忆条目，
  trigram 分词兼容中文子串匹配（无 FTS5 的环境自动退化为 LIKE）。
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from pathlib import Path

from minispark.providers.base import Message

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,          -- 整条消息的 JSON 序列化
    compacted INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, compacted, id);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
"""

_FTS_DDL = "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content, tokenize='trigram')"

_TERM_SPLIT = re.compile(r"[^\w一-鿿]+")


class MemoryStore:
    """记忆与历史的唯一存储入口（线程不敏感，单进程使用）。"""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._fts = True
        try:
            self._conn.execute(_FTS_DDL)
        except sqlite3.OperationalError:
            logger.warning("SQLite FTS5 不可用，记忆检索退化为 LIKE")
            self._fts = False
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ── 会话历史 ─────────────────────────────────────────────

    def add_message(self, session_id: str, message: Message) -> None:
        self._conn.execute(
            "INSERT INTO messages(session_id, role, content, created_at) VALUES (?,?,?,?)",
            (
                session_id,
                message.get("role", "unknown"),
                json.dumps(message, ensure_ascii=False),
                time.time(),
            ),
        )
        self._conn.commit()

    def load_messages(self, session_id: str) -> list[Message]:
        """加载会话的未压缩消息（压缩产生的摘要也在其中，历史顺序）。"""
        rows = self._conn.execute(
            "SELECT content FROM messages WHERE session_id=? AND compacted=0 ORDER BY id",
            (session_id,),
        ).fetchall()
        return [json.loads(r["content"]) for r in rows]

    def mark_compacted(self, session_id: str, count: int) -> None:
        """把最早的 count 条未压缩消息标记为已压缩（归档，不删除）。"""
        self._conn.execute(
            """UPDATE messages SET compacted=1 WHERE id IN (
                   SELECT id FROM messages
                   WHERE session_id=? AND compacted=0 ORDER BY id LIMIT ?
               )""",
            (session_id, count),
        )
        self._conn.commit()

    def list_sessions(self) -> list[dict]:
        """列出所有会话：session_id、未压缩消息数、最后活跃时间（新的在前）。"""
        rows = self._conn.execute(
            """SELECT session_id, COUNT(*) AS n, MAX(created_at) AS last
               FROM messages WHERE compacted=0
               GROUP BY session_id ORDER BY last DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str) -> int:
        """删除会话的全部消息（含已压缩归档），返回删除条数。"""
        cur = self._conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        self._conn.commit()
        return cur.rowcount

    # ── 长期记忆 ─────────────────────────────────────────────

    def save_memory(self, content: str, tags: str = "") -> int | None:
        """保存一条记忆；完全重复时返回 None（重复防护，Hermes 式）。"""
        dup = self._conn.execute("SELECT id FROM memories WHERE content=?", (content,)).fetchone()
        if dup:
            return None
        cur = self._conn.execute(
            "INSERT INTO memories(content, tags, created_at) VALUES (?,?,?)",
            (content, tags, time.time()),
        )
        if self._fts:
            self._conn.execute(
                "INSERT INTO memories_fts(rowid, content) VALUES (?,?)",
                (cur.lastrowid, content),
            )
        self._conn.commit()
        return cur.lastrowid

    def search_memories(self, query: str, limit: int = 5) -> list[dict]:
        """FTS5 全文检索（trigram 要求词长 ≥3），短词回退 LIKE 子串匹配。"""
        terms = [t for t in _TERM_SPLIT.split(query) if t]
        found: dict[int, dict] = {}

        if self._fts:
            match = " OR ".join(f'"{t}"' for t in terms if len(t) >= 3)
            if match:
                try:
                    rows = self._conn.execute(
                        """SELECT m.* FROM memories m
                           JOIN memories_fts f ON m.id = f.rowid
                           WHERE memories_fts MATCH ?
                           ORDER BY bm25(memories_fts) LIMIT ?""",
                        (match, limit),
                    ).fetchall()
                    found.update({r["id"]: dict(r) for r in rows})
                except sqlite3.OperationalError as exc:
                    logger.debug("FTS 检索失败，回退 LIKE: %s", exc)

        if len(found) < limit:
            for term in terms:
                rows = self._conn.execute(
                    "SELECT * FROM memories WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
                    (f"%{term}%", limit),
                ).fetchall()
                found.update({r["id"]: dict(r) for r in rows})

        results = sorted(found.values(), key=lambda r: r["created_at"], reverse=True)
        return results[:limit]

    def list_memories(self, limit: int = 100) -> list[dict]:
        """列出全部长期记忆（新的在前）。"""
        rows = self._conn.execute(
            "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def find_memories(self, substring: str) -> list[dict]:
        """按内容子串定位记忆（供更新/删除前的精确匹配）。"""
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE content LIKE ? ORDER BY created_at DESC",
            (f"%{substring}%",),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_memory(self, memory_id: int, content: str, tags: str | None = None) -> bool:
        """更新记忆内容并同步 FTS 索引。"""
        exists = self._conn.execute("SELECT id FROM memories WHERE id=?", (memory_id,)).fetchone()
        if not exists:
            return False
        if tags is None:
            self._conn.execute("UPDATE memories SET content=? WHERE id=?", (content, memory_id))
        else:
            self._conn.execute(
                "UPDATE memories SET content=?, tags=? WHERE id=?", (content, tags, memory_id)
            )
        if self._fts:
            self._conn.execute("DELETE FROM memories_fts WHERE rowid=?", (memory_id,))
            self._conn.execute(
                "INSERT INTO memories_fts(rowid, content) VALUES (?,?)", (memory_id, content)
            )
        self._conn.commit()
        return True

    def delete_memory(self, memory_id: int) -> bool:
        """删除记忆并同步 FTS 索引。"""
        cur = self._conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        if cur.rowcount == 0:
            return False
        if self._fts:
            self._conn.execute("DELETE FROM memories_fts WHERE rowid=?", (memory_id,))
        self._conn.commit()
        return True

    def count_memories(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()
        return row["n"]
