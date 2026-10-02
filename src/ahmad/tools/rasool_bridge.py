"""Rasool bridge — invoke the local Rasool platform as a governed tool.

Rasool (now vendored at ``ahmad-agent/rasool/``) is a local multi-agent
platform (EventBus + Services). This bridge lets Ahmad *use* Rasool as a
tool: run the GitHub intel agent and read its feed/digest output, without
granting Rasool any execution authority inside Ahmad.

Design constraints (match existing Ahmad tools such as rasool_feed_read):
- Bounded, read-mostly, subprocess-isolated to Rasool's own venv
  (Rasool pins Python <3.14, Ahmad runs 3.14, so we never import Rasool).
- Output is untrusted data, never instructions.
- Fixed allowlist of Rasool operations; no arbitrary arg passthrough.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from ahmad.core.types import EffectStatus
from ahmad.execution.mock_tool import ToolResult


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_RASOOL_DIR = _PROJECT_ROOT / "rasool"
_RASOOL_PY = _RASOOL_DIR / ".venv" / "bin" / "python"
_RASOOL_DIGEST = _RASOOL_DIR / ".venv" / "bin" / "rasool-digest"
_DEFAULT_DB = Path("~/.cache/rasool/intel_feed.sqlite").expanduser()

_SOURCE_RE = re.compile(r"^[a-z0-9_]{1,40}$")


class RasoolBridgeTool:
    """Governed, bounded bridge to the vendored Rasool platform.

    Supported actions (fixed allowlist, no shell):
      - ``status``          : report Rasool install/venv readiness
      - ``digest``          : render a bounded Markdown digest of the feed
      - ``feed_query``      : bounded read of intel_feed rows (source/limit)
    """

    name = "rasool_bridge"
    version = "1.0"

    DEFAULT_LIMIT = 10
    MAX_LIMIT = 50
    MAX_OUTPUT_CHARS = 8000
    TIMEOUT_S = 30

    _ALLOWED_ACTIONS = frozenset({"status", "digest", "feed_query", "live_search"})
    _ALLOWED_KEYS = frozenset({"action", "limit", "source", "hours", "query", "max", "sort"})
    _MAX_SEARCH = 30
    _SORT_CHOICES = frozenset({"stars", "updated", "forks", "help-wanted-issues"})
    _COLUMNS = ("source", "url", "title_original", "title_ar", "summary_ar", "score")

    def __init__(
        self,
        rasool_dir: str | Path | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        self.rasool_dir = Path(rasool_dir or _RASOOL_DIR).expanduser().resolve()
        self.python = self.rasool_dir / ".venv" / "bin" / "python"
        self.digest_bin = self.rasool_dir / ".venv" / "bin" / "rasool-digest"
        self.db_path = Path(db_path or _DEFAULT_DB).expanduser()

    # --- public entrypoint -------------------------------------------------

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

        op = args.get("action", "status")
        if op not in self._ALLOWED_ACTIONS:
            return self._fail(
                f"unknown action '{op}' (allowed: {sorted(self._ALLOWED_ACTIONS)})"
            )

        if op == "status":
            return self._status()
        if op == "digest":
            return self._digest(args)
        if op == "live_search":
            return self._live_search(args)
        return self._feed_query(args)

    # --- actions -----------------------------------------------------------

    def _status(self) -> ToolResult:
        report = {
            "rasool_dir": str(self.rasool_dir),
            "rasool_dir_exists": self.rasool_dir.is_dir(),
            "venv_python_exists": self.python.is_file(),
            "digest_bin_exists": self.digest_bin.is_file(),
            "feed_db": str(self.db_path),
            "feed_db_exists": self.db_path.is_file(),
        }
        return self._ok(report)

    def _digest(self, args: dict) -> ToolResult:
        if not self.digest_bin.is_file():
            return self._fail("rasool-digest binary not found (run rasool/install.sh)")
        hours = args.get("hours", 24)
        if isinstance(hours, bool) or not isinstance(hours, int):
            return self._fail("hours must be an integer")
        if not 1 <= hours <= 168:
            return self._fail("hours must be between 1 and 168")

        cmd = [str(self.digest_bin), "--hours", str(hours)]
        return self._run_cmd(cmd, trusted_binary=True)

    def _feed_query(self, args: dict) -> ToolResult:
        limit = args.get("limit", self.DEFAULT_LIMIT)
        if isinstance(limit, bool) or not isinstance(limit, int):
            return self._fail("limit must be an integer")
        if not 1 <= limit <= self.MAX_LIMIT:
            return self._fail(f"limit must be between 1 and {self.MAX_LIMIT}")

        source = args.get("source")
        if source is not None and (
            not isinstance(source, str) or not _SOURCE_RE.fullmatch(source)
        ):
            return self._fail("invalid source (a-z 0-9 _ up to 40 chars)")

        if not self.db_path.is_file():
            return self._fail("feed database not found")

        import sqlite3
        uri = f"file:{self.db_path}?mode=ro"
        sql = f"SELECT {', '.join(self._COLUMNS)} FROM intel_feed"
        params: list = []
        if source is not None:
            sql += " WHERE source = ?"
            params.append(source)
        sql += " ORDER BY created_at DESC, persisted_at DESC LIMIT ?"
        params.append(limit)
        try:
            conn = sqlite3.connect(uri, uri=True, timeout=2.0)
            try:
                conn.execute("PRAGMA query_only = ON")
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            return self._fail(f"feed read failed: {exc}")

        items = [
            {k: (str(v)[:500] if v is not None else None) for k, v in zip(self._COLUMNS, row)}
            for row in rows
        ]
        return self._ok({
            "origin": "rasool.feed_query",
            "untrusted_content": True,
            "count": len(items),
            "items": items,
        })

    def _live_search(self, args: dict) -> ToolResult:
        bin_path = self.rasool_dir / ".venv" / "bin" / "rasool-live-search"
        if not bin_path.is_file():
            return self._fail(
                "rasool-live-search binary not found (reinstall rasool editable)"
            )

        query = args.get("query")
        if not isinstance(query, str) or not (1 <= len(query.strip()) <= 200):
            return self._fail("query is required (1-200 chars)")

        max_results = args.get("max", 10)
        if isinstance(max_results, bool) or not isinstance(max_results, int):
            return self._fail("max must be an integer")
        if not 1 <= max_results <= self._MAX_SEARCH:
            return self._fail(f"max must be between 1 and {self._MAX_SEARCH}")

        sort = args.get("sort", "stars")
        if not isinstance(sort, str) or sort not in self._SORT_CHOICES:
            return self._fail(f"sort must be one of {sorted(self._SORT_CHOICES)}")

        cmd = [
            str(bin_path),
            "--query",
            query.strip(),
            "--max",
            str(max_results),
            "--sort",
            sort,
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.rasool_dir),
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_S,
                env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home())},
            )
        except subprocess.TimeoutExpired:
            return self._fail(f"live_search timed out after {self.TIMEOUT_S}s")
        except OSError as exc:
            return self._fail(f"failed to execute live_search: {exc}")

        if proc.returncode != 0:
            return self._fail(
                (proc.stderr or "live_search failed").strip()[: self.MAX_OUTPUT_CHARS]
            )

        raw = (proc.stdout or "").strip()
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            return self._fail(f"live_search returned invalid JSON: {exc}")
        if not isinstance(payload, dict):
            return self._fail("live_search returned non-object JSON")

        items = payload.get("items")
        if not isinstance(items, list):
            return self._fail("live_search payload missing items list")

        return self._ok({
            "origin": "rasool.live_search",
            "untrusted_content": True,
            "query": query.strip(),
            "count": len(items),
            "items": items,
        })

    # --- helpers -----------------------------------------------------------

    def _run_cmd(self, cmd: list[str], *, trusted_binary: bool) -> ToolResult:
        if not trusted_binary:
            return self._fail("untrusted binary rejected")
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.rasool_dir),
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_S,
                env={"PATH": "/usr/bin:/bin"},
            )
        except subprocess.TimeoutExpired:
            return self._fail(f"command timed out after {self.TIMEOUT_S}s")
        except OSError as exc:
            return self._fail(f"failed to execute: {exc}")

        output = (proc.stdout or "")[: self.MAX_OUTPUT_CHARS]
        if proc.returncode != 0:
            return ToolResult(
                success=False,
                tool=self.name,
                output=(proc.stderr or output)[: self.MAX_OUTPUT_CHARS],
                effect_status=EffectStatus.NOT_APPLIED,
            )
        return self._ok({
            "origin": "rasool.bridge",
            "untrusted_content": True,
            "output": output,
        })

    def _ok(self, payload: dict) -> ToolResult:
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
