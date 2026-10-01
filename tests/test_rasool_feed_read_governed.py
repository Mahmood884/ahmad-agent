"""حوكمة rasool_feed_read: البوابة والسياسة الحقيقية وخادم MCP."""
from __future__ import annotations

import importlib
import json
import sqlite3

import pytest

from ahmad.core.events import DecisionEvent
from ahmad.core.types import EffectStatus, Mode, Scope
from ahmad.execution.gateway import ExecutionGateway
from ahmad.execution.registry import ToolRegistry
from ahmad.governance.policy import PolicyEngine
from ahmad.memory.store import MemoryStore
from ahmad.tools.rasool_feed_read import RasoolFeedReadTool

_SCHEMA = """
CREATE TABLE intel_feed (
    id TEXT PRIMARY KEY, source TEXT NOT NULL, url TEXT NOT NULL UNIQUE,
    title_original TEXT NOT NULL, title_ar TEXT NOT NULL, summary_ar TEXT NOT NULL,
    score REAL NOT NULL, status TEXT NOT NULL CHECK (status = 'persisted'),
    created_at TEXT NOT NULL, persisted_at REAL NOT NULL
);
"""


def _make_db(path, n=5):
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    for i in range(n):
        conn.execute(
            "INSERT INTO intel_feed VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"id{i}", "github_trending", f"https://example.com/{i}", f"t{i}",
             f"ع{i}", "م", 0.0, "persisted", f"2026-10-01T08:0{i}:00Z", 1000.0 + i),
        )
    conn.commit()
    conn.close()


def _run(gateway, memory, action, binding_id, tag):
    decision = gateway.policy.evaluate(
        action, Mode.GENERAL, Scope.PERSONAL, tool_binding_id=binding_id
    )
    event = DecisionEvent.from_decision(
        decision, event_id=f"{tag}-d", request_id=f"{tag}-req", timestamp_ms=1000
    )
    memory.append(event)
    return gateway.execute(
        decision, decision_event_id=event.event_id,
        result_event_id=f"{tag}-r", request_id=f"{tag}-req",
    )


@pytest.fixture()
def env(tmp_path):
    db = tmp_path / "feed.sqlite"
    _make_db(db)
    memory = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(memory=memory, digest_key_path=tmp_path / "digest.key")
    gateway.registry.replace_tool("rasool_feed_read", RasoolFeedReadTool(db))
    return gateway, memory, gateway.binding_id_for_action("rasool_feed_read")


def test_policy_allows_only_exact_prefix():
    policy = PolicyEngine()
    ok = policy.evaluate("rasool_feed_read:{}", Mode.GENERAL, Scope.PERSONAL,
                         tool_binding_id="rasool_feed_read|x")
    assert ok.allowed
    for bad in (None, "rasool_feed_read2|x", "rasool_feed_readx|x", "read_feed|x"):
        d = policy.evaluate("rasool_feed_read:{}", Mode.GENERAL, Scope.PERSONAL,
                            tool_binding_id=bad)
        assert not d.allowed


def test_gateway_executes_registered_binding(env):
    gateway, memory, binding_id = env
    r = _run(gateway, memory, 'rasool_feed_read:{"limit": 3}', binding_id, "ok")
    assert r.success is True
    data = json.loads(r.output)
    assert data["count"] == 3 and data["untrusted_content"] is True


def test_gateway_denies_forged_binding(env):
    gateway, memory, _ = env
    forged = "rasool_feed_read|rasool_feed_read|1.0|ahmad.rasool-feed-read/v1|1|" + "0" * 64
    r = _run(gateway, memory, "rasool_feed_read:{}", forged, "forged")
    assert r.success is False and r.output == "EXECUTION_DENIED"


def test_failed_call_is_no_effect_and_not_ambiguous(env):
    gateway, memory, binding_id = env
    r = _run(gateway, memory, 'rasool_feed_read:{"limit": 0}', binding_id, "bad")
    assert r.success is False
    assert r.effect_status is EffectStatus.NOT_APPLIED
    assert not any(e.get("event_type") == "attempt_ambiguous" for e in memory.read_all())


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    mod = importlib.import_module("ahmad.mcp.server")
    db = tmp_path / "feed.sqlite"
    _make_db(db)
    old = mod._gateway.registry._items["rasool_feed_read"]
    new = ToolRegistry._make_binding(
        old.action, old.metadata, RasoolFeedReadTool(db), old.generation
    )
    assert new.binding_id == old.binding_id
    monkeypatch.setitem(mod._gateway.registry._items, "rasool_feed_read", new)
    return mod


def _rpc(mod, capsys, method, params=None):
    mod.handle_request({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    return capsys.readouterr().out


def test_mcp_tools_list_exposes_tool(server, capsys):
    out = _rpc(server, capsys, "tools/list")
    msg = json.loads(out.strip().splitlines()[-1])
    tool = next(t for t in msg["result"]["tools"] if t["name"] == "rasool_feed_read")
    assert tool["inputSchema"]["additionalProperties"] is False


def test_mcp_tools_call_reads_feed(server, capsys):
    out = _rpc(server, capsys, "tools/call",
               {"name": "rasool_feed_read", "arguments": {"limit": 2}})
    assert "rasool.intel_feed" in out and "untrusted_content" in out


def test_mcp_tools_call_rejects_unknown_argument(server, capsys):
    out = _rpc(server, capsys, "tools/call",
               {"name": "rasool_feed_read", "arguments": {"db": "/etc/passwd"}})
    assert "unknown arguments" in out
