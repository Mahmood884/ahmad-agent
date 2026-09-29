"""Per-OS-user SQLite full-text memory with explicit deletion."""
from __future__ import annotations

import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from ahmad.memory.sqlite_encryption import (
    connect_encrypted,
    load_encryption_key,
    require_sqlcipher,
)


class LocalMemoryStore:
    """Small local lexical memory store partitioned by operating-system user."""

    MAX_CONTENT_CHARS = 10_000
    MAX_QUERY_CHARS = 500
    MAX_RESULTS = 20

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        owner_id: str | None = None,
        key_path: str | Path | None = None,
    ) -> None:
        self.path = (
            Path(path).expanduser()
            if path is not None
            else Path.home() / ".local" / "share" / "ahmad-agent" / "memories.sqlite3"
        )
        self.owner_id = owner_id or self._current_owner_id()
        self._key = load_encryption_key(key_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    memory_id UNINDEXED,
                    owner_id UNINDEXED,
                    content,
                    tokenize='unicode61'
                )
                """
            )

    @staticmethod
    def _current_owner_id() -> str:
        if hasattr(os, "getuid"):
            return f"uid:{os.getuid()}"
        return f"user:{Path.home().resolve()}"

    def _connect(self) -> Any:
        connection = connect_encrypted(
            self.path,
            self._key,
            timeout=10,
            row_factory=require_sqlcipher().Row,
        )
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def add(self, content: str) -> int:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content must be a non-empty string")
        content = content.strip()
        if len(content) > self.MAX_CONTENT_CHARS:
            raise ValueError(f"content exceeds {self.MAX_CONTENT_CHARS} characters")
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO memories(owner_id, content, created_at) VALUES(?, ?, ?)",
                (self.owner_id, content, created_at),
            )
            memory_id = int(cursor.lastrowid)
            connection.execute(
                "INSERT INTO memories_fts(memory_id, owner_id, content) VALUES(?, ?, ?)",
                (memory_id, self.owner_id, content),
            )
        return memory_id

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, str | int]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        query = query.strip()
        if len(query) > self.MAX_QUERY_CHARS:
            raise ValueError(f"query exceeds {self.MAX_QUERY_CHARS} characters")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= self.MAX_RESULTS:
            raise ValueError(f"limit must be between 1 and {self.MAX_RESULTS}")
        terms = re.findall(r"[\w]+", query, flags=re.UNICODE)
        if not terms:
            return []
        fts_query = " AND ".join(f'"{term}"' for term in terms)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT m.id, m.content, m.created_at
                FROM memories_fts
                JOIN memories AS m ON m.id = CAST(memories_fts.memory_id AS INTEGER)
                WHERE memories_fts MATCH ? AND m.owner_id = ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, self.owner_id, limit),
            ).fetchall()
        return [
            {"id": int(row["id"]), "content": row["content"], "created_at": row["created_at"]}
            for row in rows
        ]

    def forget(self, memory_id: int) -> bool:
        if not isinstance(memory_id, int) or isinstance(memory_id, bool) or memory_id <= 0:
            raise ValueError("memory_id must be a positive integer")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id FROM memories WHERE id=? AND owner_id=?",
                (memory_id, self.owner_id),
            ).fetchone()
            if row is None:
                return False
            connection.execute(
                "DELETE FROM memories_fts WHERE memory_id=? AND owner_id=?",
                (memory_id, self.owner_id),
            )
            connection.execute(
                "DELETE FROM memories WHERE id=? AND owner_id=?",
                (memory_id, self.owner_id),
            )
        with self._connection() as connection:
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            if journal_mode.lower() == "wal":
                checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if checkpoint[0]:
                    raise require_sqlcipher().OperationalError(
                        "could not checkpoint WAL before secure vacuum"
                    )
            connection.execute("VACUUM")
            if journal_mode.lower() == "wal":
                checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if checkpoint[0]:
                    raise require_sqlcipher().OperationalError(
                        "could not truncate WAL after secure vacuum"
                    )
        return True
