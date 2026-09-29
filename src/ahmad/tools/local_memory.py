"""MCP-callable tools for the current OS user's private local memory."""
from __future__ import annotations

import json
import sqlite3

from ahmad.execution.mock_tool import ToolResult
from ahmad.memory.local_memory import LocalMemoryStore


class _MemoryTool:
    def __init__(self, store: LocalMemoryStore | None = None) -> None:
        self._store = store

    @property
    def store(self) -> LocalMemoryStore:
        if self._store is None:
            self._store = LocalMemoryStore()
        return self._store

    def _payload(self, action: str) -> dict:
        prefix = f"{self.name}:"
        if not action.startswith(prefix):
            raise ValueError(f"Action must start with '{prefix}'")
        try:
            payload = json.loads(action[len(prefix):])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Action payload must be valid JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError("Action payload must be a JSON object")
        return payload

    def _error(self, exc: Exception) -> ToolResult:
        return ToolResult(False, self.name, f"ERROR: {exc}", None)


class MemoryAddTool(_MemoryTool):
    name = "memory_add"
    version = "1.0"

    def run(self, action: str) -> ToolResult:
        try:
            payload = self._payload(action)
            memory_id = self.store.add(payload.get("content"))
            return ToolResult(
                True,
                self.name,
                json.dumps({"id": memory_id, "message": "Memory saved locally."}),
                None,
            )
        except (ValueError, sqlite3.Error) as exc:
            return self._error(exc)


class MemorySearchTool(_MemoryTool):
    name = "memory_search"
    version = "1.0"

    def run(self, action: str) -> ToolResult:
        try:
            payload = self._payload(action)
            matches = self.store.search(
                payload.get("query"),
                limit=payload.get("limit", 10),
            )
            return ToolResult(True, self.name, json.dumps(matches, ensure_ascii=False, indent=2), None)
        except (ValueError, sqlite3.Error) as exc:
            return self._error(exc)


class MemoryForgetTool(_MemoryTool):
    name = "memory_forget"
    version = "1.0"

    def run(self, action: str) -> ToolResult:
        try:
            payload = self._payload(action)
            memory_id = payload.get("id")
            if not isinstance(memory_id, int) or isinstance(memory_id, bool):
                raise ValueError("id must be an integer")
            forgotten = self.store.forget(memory_id)
            if not forgotten:
                return ToolResult(
                    False, self.name, "NOT_FOUND: no memory with that ID for this OS user", None
                )
            return ToolResult(
                True, self.name, json.dumps({"id": memory_id, "message": "Memory deleted."}), None
            )
        except (ValueError, sqlite3.Error) as exc:
            return self._error(exc)
