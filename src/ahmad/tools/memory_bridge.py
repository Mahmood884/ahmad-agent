"""Governed bridge to mcp-memory-service (stdio subprocess).

Pattern: identical to rasool_bridge — fixed action allowlist, bounded args,
subprocess isolation, untrusted_content tagging on EVERY response, and a
``run(action) -> ToolResult`` entrypoint so the gateway/registry can bind it.

Upstream: python -m mcp_memory_service.server  (stdio — NOT the HTTP binary)
Env:      MCP_MEMORY_BASE_DIR / MCP_MEMORY_USE_ONNX / MCP_MEMORY_ONNX_ALLOW_DOWNLOAD
Contract: store | search | get_by_tag | recent | stats   (delete DEFERRED)
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from ahmad.core.types import EffectStatus
from ahmad.execution.mock_tool import ToolResult

_MEMORY_ROOT = Path.home() / "ahmad-agent" / "memory-service"
_SERVER_PY = _MEMORY_ROOT / ".venv" / "bin" / "python"
_BASE_DIR = Path.home() / "ahmad-agent" / "data" / "memory"

# -- Hard limits (mirrored 1:1 in mcp/server.py JSON schema) --
MAX_CONTENT = 8_000
MAX_TAGS = 10
MAX_TAG_LEN = 64
MAX_QUERY = 512
MAX_LIMIT = 50
MAX_PAGE_SIZE = 50
SEARCH_MODES = ("semantic", "exact", "hybrid", "ranked")
TIMEOUT_S = 60

_ALLOWED_ACTIONS = frozenset({"store", "search", "get_by_tag", "recent", "stats"})
_ALLOWED_KEYS = frozenset({
    "action", "content", "tags", "query", "mode", "limit", "page", "page_size",
})


def _env() -> dict:
    return {
        **os.environ,
        "MCP_MEMORY_BASE_DIR": str(_BASE_DIR),
        "MCP_MEMORY_USE_ONNX": "1",
        "MCP_MEMORY_ONNX_ALLOW_DOWNLOAD": "1",
    }


def _extract(res):
    """MCP CallToolResult -> plain payload (structured first, then JSON text)."""
    sc = getattr(res, "structuredContent", None)
    if sc is not None:
        return sc
    if getattr(res, "content", None):
        text = res.content[0].text
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError, AttributeError):
            return text
    return str(res)


def _mcp_session(calls):
    """One stdio session; executes [(tool, args), ...] in order."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def _run():
        params = StdioServerParameters(
            command=str(_SERVER_PY),
            args=["-m", "mcp_memory_service.server"],
            env=_env(),
        )
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                out = []
                for tool, tool_args in calls:
                    res = await s.call_tool(tool, tool_args)
                    if getattr(res, "isError", False):
                        msg = res.content[0].text if res.content else "unknown tool error"
                        raise RuntimeError(f"{tool}: {msg}"[:300])
                    out.append(_extract(res))
                return out

    return asyncio.run(asyncio.wait_for(_run(), timeout=TIMEOUT_S))


# -- Bounds — pure checks; no subprocess is touched before them --
def _int_in(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _bad_tags(tags):
    if not isinstance(tags, list) or len(tags) > MAX_TAGS:
        return True
    return any(
        not isinstance(t, str) or not (1 <= len(t.strip()) <= MAX_TAG_LEN)
        for t in tags
    )


def _bounds(action, a):
    """Return an error message or None."""
    if action == "store":
        c = a.get("content")
        if not isinstance(c, str) or not c.strip():
            return "content must be a non-empty string"
        if len(c) > MAX_CONTENT:
            return f"content exceeds {MAX_CONTENT} chars"
        if _bad_tags(a.get("tags", [])):
            return "invalid tags (max 10, each 1..64 chars)"
    elif action == "search":
        q = a.get("query")
        if not isinstance(q, str) or not (1 <= len(q) <= MAX_QUERY):
            return f"query must be a string 1..{MAX_QUERY} chars"
        if a.get("mode", "semantic") not in SEARCH_MODES:
            return "mode must be semantic|exact|hybrid|ranked"
        if _bad_tags(a.get("tags", [])):
            return "invalid tags"
        if not _int_in(a.get("limit", 5), 1, MAX_LIMIT):
            return f"limit must be int 1..{MAX_LIMIT}"
    elif action == "get_by_tag":
        if _bad_tags(a.get("tags")):
            return "tags required (1..10 items, each 1..64 chars)"
        if not _int_in(a.get("limit", 20), 1, MAX_LIMIT):
            return f"limit must be int 1..{MAX_LIMIT}"
    elif action == "recent":
        if not _int_in(a.get("page", 1), 1, 10_000):
            return "page must be int >= 1"
        if not _int_in(a.get("page_size", 10), 1, MAX_PAGE_SIZE):
            return f"page_size must be int 1..{MAX_PAGE_SIZE}"
    return None


# -- Mapping — action -> [(tool, args), ...] --
def _build_calls(action, a):
    if action == "store":
        return [("memory_store", {
            "content": a["content"].strip(),
            "metadata": {"tags": [t.strip() for t in a.get("tags", [])]},
        })]
    if action == "search":
        call = {"query": a["query"], "mode": a.get("mode", "semantic"),
                "limit": a.get("limit", 5)}
        if a.get("tags"):
            call["tags"] = [t.strip() for t in a["tags"]]
        return [("memory_search", call)]
    if action == "get_by_tag":
        return [("memory_search", {
            "tags": [t.strip() for t in a["tags"]],
            "limit": a.get("limit", 20),
        })]
    if action == "recent":
        return [("memory_list", {"page": a.get("page", 1),
                                 "page_size": a.get("page_size", 10)})]
    if action == "stats":
        return [("memory_stats", {}), ("memory_health", {})]
    return []


def _dispatch(args: dict) -> dict:
    """Core logic; returns a plain dict payload (untrusted)."""
    # 1) args must be an object (defensively accept a JSON string)
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = None
    if not isinstance(args, dict):
        return {"untrusted_content": True, "error": "args must be a JSON object"}

    unknown = set(args) - _ALLOWED_KEYS
    if unknown:
        return {"untrusted_content": True, "error": "unknown_arguments",
                "detail": sorted(unknown)}

    # 2) fixed allowlist — reject before any spawn
    action = args.get("action")
    if action not in _ALLOWED_ACTIONS:
        return {"untrusted_content": True, "error": "unknown_action",
                "action": str(action)[:64], "allowed": sorted(_ALLOWED_ACTIONS)}

    # 3) bounds — reject before any spawn
    err = _bounds(action, args)
    if err:
        return {"untrusted_content": True, "error": "bounds_violation", "detail": err}

    # 4) execute through the isolated session
    try:
        results = _mcp_session(_build_calls(action, args))
    except asyncio.TimeoutError:
        return {"untrusted_content": True, "error": "memory_timeout", "timeout_s": TIMEOUT_S}
    except FileNotFoundError:
        return {"untrusted_content": True, "error": "memory_service_missing",
                "detail": str(_SERVER_PY)}
    except Exception as e:  # no raw traceback ever reaches the agent
        return {"untrusted_content": True, "error": "memory_failure",
                "detail": f"{type(e).__name__}: {e}"[:200]}

    payload = results[0] if len(results) == 1 else {
        k: v for k, v in zip(("stats", "health"), results)}
    return {"untrusted_content": True, "action": action, "result": payload}


class MemoryBridgeTool:
    """Governed, bounded bridge to mcp-memory-service.

    Supported actions (fixed allowlist, no shell):
      - ``store``       : memory_store(content, metadata.tags)
      - ``search``      : memory_search(query, mode, tags?, limit)
      - ``get_by_tag``  : memory_search(tags, limit)  [no query]
      - ``recent``      : memory_list(page, page_size)
      - ``stats``       : memory_stats + memory_health
      - ``delete``      : DEFERRED (not exposed)
    """

    name = "memory_bridge"
    version = "1.0"

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

        payload = _dispatch(args)
        if isinstance(payload, dict) and payload.get("error"):
            return self._fail(json.dumps(payload, ensure_ascii=False))
        return self._ok(payload)

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
