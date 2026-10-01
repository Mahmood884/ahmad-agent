"""Read-only access to the local Rasool intel_feed database."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote

from ahmad.core.types import EffectStatus
from ahmad.execution.mock_tool import ToolResult


class RasoolFeedReadTool:
    """Read a bounded selection of items from Rasool's local feed."""

    name = "rasool_feed_read"
    version = "1.0"

    DEFAULT_DB = "~/.cache/rasool/intel_feed.sqlite"
    DEFAULT_LIMIT = 10
    MAX_LIMIT = 50
    MAX_FIELD_CHARS = 500

    _ALLOWED_KEYS = frozenset({"limit", "source"})
    _SOURCE_RE = re.compile(r"^[a-z0-9_]{1,40}$")
    _COLUMNS = (
        "id", "source", "url", "title_original",
        "title_ar", "summary_ar", "score", "created_at",
    )
    _TEXT_COLUMNS = frozenset({
        "id", "source", "url", "title_original",
        "title_ar", "summary_ar", "created_at",
    })

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or self.DEFAULT_DB).expanduser().resolve()

    def run(self, action: str) -> ToolResult:
        raw = action.strip()
        if raw.startswith(f"{self.name}:"):
            raw = raw[len(self.name) + 1:].strip()
        elif raw == self.name:
            raw = ""

        try:
            args = json.loads(raw) if raw else {}
        except ValueError as exc:
            return self._fail(f"invalid arguments JSON: {exc}")
        if not isinstance(args, dict):
            return self._fail("arguments must be a JSON object")

        unknown = set(args) - self._ALLOWED_KEYS
        if unknown:
            return self._fail(f"unknown arguments: {sorted(unknown)}")

        limit = args.get("limit", self.DEFAULT_LIMIT)
        if isinstance(limit, bool) or not isinstance(limit, int):
            return self._fail("limit must be an integer")
        if not 1 <= limit <= self.MAX_LIMIT:
            return self._fail(f"limit must be between 1 and {self.MAX_LIMIT}")

        source = args.get("source")
        if source is not None:
            if not isinstance(source, str) or not self._SOURCE_RE.fullmatch(source):
                return self._fail(
                    "invalid source (allowed: a-z 0-9 _ up to 40 chars)"
                )

        if not self.db_path.is_file():
            return self._fail("feed database not found")

        sql = f"SELECT {', '.join(self._COLUMNS)} FROM intel_feed"
        params: list[str | int] = []
        if source is not None:
            sql += " WHERE source = ?"
            params.append(source)
        sql += " ORDER BY created_at DESC, persisted_at DESC LIMIT ?"
        params.append(limit)

        uri = f"file:{quote(str(self.db_path))}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=2.0)
            try:
                conn.execute("PRAGMA query_only = ON")
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            return self._fail(f"feed read failed: {exc}")

        items = []
        for row in rows:
            item = dict(zip(self._COLUMNS, row))
            for column in self._TEXT_COLUMNS:
                item[column] = str(item[column])[:self.MAX_FIELD_CHARS]
            items.append(item)

        payload = {
            "origin": "rasool.intel_feed",
            "untrusted_content": True,
            "count": len(items),
            "items": items,
        }
        return ToolResult(
            success=True,
            tool=self.name,
            output=json.dumps(payload, ensure_ascii=False),
            effect_status=EffectStatus.NOT_APPLIED,
        )

    def _fail(self, message: str) -> ToolResult:
        return ToolResult(
            success=False,
            tool=self.name,
            output=message,
            effect_status=EffectStatus.NOT_APPLIED,
        )
