"""Tests for the governed memory_bridge (subprocess-isolated).

All tests monkeypatch _mcp_session so NO real subprocess/service is spawned.
"""
import json

from ahmad.tools import memory_bridge as mb


class _Res:
    def __init__(self, payload, is_error=False):
        self.structuredContent = payload
        self.content = []
        self.isError = is_error


def _patch(monkeypatch, capture):
    def fake(calls):
        capture.append(calls)
        # return one payload per call
        out = []
        for tool, _args in calls:
            out.append({"tool": tool, "ok": True})
        return out
    monkeypatch.setattr(mb, "_mcp_session", fake)


def test_unknown_action_no_spawn(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    res = mb._dispatch({"action": "delete_all"})
    assert res["error"] == "unknown_action"
    assert calls == []  # subprocess never touched


def test_unknown_argument_rejected(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    res = mb._dispatch({"action": "store", "content": "x", "bogus": 1})
    assert res["error"] == "unknown_arguments"
    assert calls == []


def test_store_content_too_long(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    res = mb._dispatch({"action": "store", "content": "x" * 8001})
    assert res["error"] == "bounds_violation"
    assert calls == []


def test_store_requires_content(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    res = mb._dispatch({"action": "store", "content": "   "})
    assert res["error"] == "bounds_violation"
    assert calls == []


def test_search_limit_out_of_range(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    for bad in (0, 100):
        res = mb._dispatch({"action": "search", "query": "q", "limit": bad})
        assert res["error"] == "bounds_violation"
    assert calls == []


def test_search_bad_mode(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    res = mb._dispatch({"action": "search", "query": "q", "mode": "voodoo"})
    assert res["error"] == "bounds_violation"


def test_get_by_tag_requires_tags(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    res = mb._dispatch({"action": "get_by_tag"})
    assert res["error"] == "bounds_violation"


def test_recent_page_size_bounds(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    res = mb._dispatch({"action": "recent", "page_size": 51})
    assert res["error"] == "bounds_violation"


def test_mapping_store(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    res = mb._dispatch({"action": "store", "content": " hello ", "tags": [" a ", "b"]})
    assert res["untrusted_content"] is True
    tool, args = calls[0][0]
    assert tool == "memory_store"
    assert args["content"] == "hello"
    assert args["metadata"]["tags"] == ["a", "b"]


def test_mapping_search(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    mb._dispatch({"action": "search", "query": "esp32", "tags": ["hardware"], "limit": 5})
    tool, args = calls[0][0]
    assert tool == "memory_search"
    assert args["query"] == "esp32" and args["mode"] == "semantic"
    assert args["tags"] == ["hardware"] and args["limit"] == 5


def test_mapping_search_without_tags(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    mb._dispatch({"action": "search", "query": "q"})
    _, args = calls[0][0]
    assert "tags" not in args


def test_mapping_get_by_tag(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    mb._dispatch({"action": "get_by_tag", "tags": ["x"]})
    tool, args = calls[0][0]
    assert tool == "memory_search"
    assert args["tags"] == ["x"] and "query" not in args


def test_mapping_recent(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    mb._dispatch({"action": "recent", "page": 2, "page_size": 10})
    tool, args = calls[0][0]
    assert tool == "memory_list"
    assert args == {"page": 2, "page_size": 10}


def test_mapping_stats_two_calls(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    res = mb._dispatch({"action": "stats"})
    tools = [t for t, _ in calls[0]]
    assert tools == ["memory_stats", "memory_health"]
    assert set(res["result"].keys()) == {"stats", "health"}


def test_untrusted_flag_on_success_and_error(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    ok = mb._dispatch({"action": "recent"})
    assert ok["untrusted_content"] is True
    err = mb._dispatch({"action": "nope"})
    assert err["untrusted_content"] is True


def test_subprocess_failure_is_structured(monkeypatch):
    def boom(calls):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(mb, "_mcp_session", boom)
    res = mb._dispatch({"action": "recent"})
    assert res["error"] == "memory_failure"
    assert "kaboom" in res["detail"]
    assert res["untrusted_content"] is True


def test_timeout_is_structured(monkeypatch):
    import asyncio
    def slow(calls):
        raise asyncio.TimeoutError()
    monkeypatch.setattr(mb, "_mcp_session", slow)
    res = mb._dispatch({"action": "recent"})
    assert res["error"] == "memory_timeout"


def test_args_string_defensive(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    res = mb._dispatch(json.dumps({"action": "recent"}))
    assert "error" not in res


def test_tool_run_success(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    tool = mb.MemoryBridgeTool()
    out = tool.run(json.dumps({"action": "recent"}))
    assert out.success is True
    assert "untrusted_content" in out.output


def test_tool_run_failure(monkeypatch):
    calls = []
    _patch(monkeypatch, calls)
    tool = mb.MemoryBridgeTool()
    out = tool.run(json.dumps({"action": "delete_all"}))
    assert out.success is False
    assert "unknown_action" in out.output
