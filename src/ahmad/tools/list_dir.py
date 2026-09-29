"""ListDirTool — lists a directory's immediate entries, safely bounded.

Contract:
    tool.run(action: str) -> ToolResult

Action forms:
    "<path>"              -> list entries in <path>
    "list_dir:<path>"     -> same, explicit form
    "" / "list_dir"       -> list entries in root

Guards mirror ReadFileTool: path must resolve under the configured root
(default: $HOME), must exist and be a directory, entry count is capped.
No side effects; always EffectStatus.NOT_APPLIED.
"""
from __future__ import annotations

from pathlib import Path

from ahmad.core.types import EffectStatus
from ahmad.execution.mock_tool import ToolResult


class ListDirTool:
    name = "list_dir"
    version = "1.0"

    MAX_ENTRIES = 500

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root).expanduser().resolve() if root else Path.home().resolve()

    def run(self, action: str) -> ToolResult:
        raw = action.strip()
        if raw.startswith(f"{self.name}:"):
            raw = raw[len(self.name) + 1:].strip()
        target = raw or str(self.root)

        try:
            path = Path(target).expanduser().resolve()
        except (OSError, RuntimeError) as exc:
            return self._fail(f"invalid path: {exc}")

        try:
            path.relative_to(self.root)
        except ValueError:
            return self._fail(f"path outside allowed root: {path}")

        if not path.exists():
            return self._fail(f"not found: {path}")
        if not path.is_dir():
            return self._fail(f"not a directory: {path}")

        try:
            entries = sorted(path.iterdir(), key=lambda p: p.name)
        except OSError as exc:
            return self._fail(f"listing failed: {exc}")

        truncated = len(entries) > self.MAX_ENTRIES
        entries = entries[: self.MAX_ENTRIES]

        lines = []
        for entry in entries:
            try:
                kind = "dir" if entry.is_dir() else "file"
                size = entry.stat().st_size if kind == "file" else ""
            except OSError:
                kind, size = "?", ""
            lines.append(f"{kind}\t{size}\t{entry.name}")

        output = "\n".join(lines)
        if truncated:
            output += f"\n... truncated at {self.MAX_ENTRIES} entries"

        return ToolResult(
            success=True,
            tool=self.name,
            output=output,
            effect_status=EffectStatus.NOT_APPLIED,
        )

    def _fail(self, message: str) -> ToolResult:
        return ToolResult(
            success=False,
            tool=self.name,
            output=message,
            effect_status=EffectStatus.NOT_APPLIED,
        )
