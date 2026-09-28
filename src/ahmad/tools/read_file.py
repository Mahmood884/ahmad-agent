"""ReadFileTool — reads a file from disk with size and path guards.

Contract:
    tool.run(action: str) -> ToolResult

The action string is expected to be:
    "<path>"                  → read the file at <path>
    "read_file:<path>"        → same, explicit form

Path resolution:
    - ~ is expanded
    - Must be an existing regular file
    - Must be under the configured root (default: $HOME)
    - Must not exceed MAX_SIZE bytes

No side effects; always EffectStatus.NOT_APPLIED.
"""
from __future__ import annotations

from pathlib import Path

from ahmad.core.types import EffectStatus
from ahmad.execution.mock_tool import ToolResult


class ReadFileTool:
    """Read a file from disk, safely bounded."""

    name = "read_file"
    version = "1.0"

    MAX_SIZE = 1_000_000  # 1 MB

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root).expanduser().resolve() if root else Path.home().resolve()

    def run(self, action: str) -> ToolResult:
        raw = action.strip()
        if raw.startswith(f"{self.name}:"):
            raw = raw[len(self.name) + 1:].strip()
        if not raw:
            return self._fail("missing path")

        try:
            path = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError) as exc:
            return self._fail(f"invalid path: {exc}")

        # Guard: must be under root
        try:
            path.relative_to(self.root)
        except ValueError:
            return self._fail(f"path outside allowed root: {path}")

        if not path.exists():
            return self._fail(f"not found: {path}")
        if not path.is_file():
            return self._fail(f"not a regular file: {path}")

        try:
            size = path.stat().st_size
        except OSError as exc:
            return self._fail(f"stat failed: {exc}")

        if size > self.MAX_SIZE:
            return self._fail(f"too large: {size} bytes (max {self.MAX_SIZE})")

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return self._fail(f"read failed: {exc}")

        return ToolResult(
            success=True,
            tool=self.name,
            output=content,
            effect_status=EffectStatus.NOT_APPLIED,
        )

    def _fail(self, message: str) -> ToolResult:
        return ToolResult(
            success=False,
            tool=self.name,
            output=message,
            effect_status=EffectStatus.NOT_APPLIED,
        )
