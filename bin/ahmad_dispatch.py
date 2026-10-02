#!/usr/bin/env python3
"""Ahmad governed dispatcher — non-interactive bridge for Agent Zero.

Reads a single JSON request from stdin and executes it through Ahmad's
ExecutionGateway (policy-checked, binding-verified, event-logged).

Request shape:
    {"action": "<tool>", "args": {...}}      # dispatch one governed tool
    {"action": "__list__"}                   # list governed tools
    {"action": "__events__", "limit": 10}   # read recent governance events

Response shape (always JSON, exit 0):
    {"ok": true, "tool": ..., "output": ..., "decision": {...}, "event_id": ...}
    {"ok": false, "error": "..."}

Design: intelligence lives in Agent Zero; this script only *executes*
approved actions under Ahmad's governance. No free-form LLM here.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Make src importable without installation
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ahmad.core.events import DecisionEvent  # noqa: E402
from ahmad.core.types import Mode, Scope  # noqa: E402
from ahmad.execution.gateway import ExecutionGateway  # noqa: E402
from ahmad.memory.store import MemoryStore  # noqa: E402

_EVENT_STORE = Path(__file__).resolve().parents[1] / "data" / "dispatch-events.jsonl"


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _build_gateway() -> ExecutionGateway:
    _EVENT_STORE.parent.mkdir(parents=True, exist_ok=True)
    return ExecutionGateway(memory=MemoryStore(_EVENT_STORE))


def _list_tools(gateway: ExecutionGateway) -> dict:
    tools = []
    for binding in gateway.registry.list():
        tools.append({
            "action": binding.action,
            "name": binding.metadata.name,
            "version": binding.metadata.version,
            "risk": binding.metadata.risk,
            "capabilities": list(binding.metadata.capabilities),
        })
    return {"ok": True, "tools": tools}


def _events(gateway: ExecutionGateway, limit: int) -> dict:
    events = gateway.memory.read_all()
    tail = events[-max(1, min(limit, 200)):]
    slim = []
    for ev in tail:
        slim.append({
            "type": ev.get("event_type"),
            "action": ev.get("action"),
            "allowed": ev.get("allowed"),
            "success": ev.get("success"),
            "tool": ev.get("tool"),
        })
    return {"ok": True, "count": len(slim), "events": slim}


def main() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        _emit({"ok": False, "error": "empty request"})
        return 0
    try:
        req = json.loads(raw)
    except ValueError as exc:
        _emit({"ok": False, "error": f"invalid json: {exc}"})
        return 0
    if not isinstance(req, dict) or "action" not in req:
        _emit({"ok": False, "error": "request must be an object with 'action'"})
        return 0

    gateway = _build_gateway()
    action = str(req["action"])

    if action == "__list__":
        _emit(_list_tools(gateway))
        return 0
    if action == "__events__":
        try:
            limit = int(req.get("limit", 10))
        except (TypeError, ValueError):
            limit = 10
        _emit(_events(gateway, limit))
        return 0

    args = req.get("args", None)
    if isinstance(args, dict):
        # JSON-style tools (e.g. rasool_bridge) expect a JSON object.
        action_str = (
            f"{action}:{json.dumps(args, ensure_ascii=False)}" if args else action
        )
    elif isinstance(args, str):
        # Plain-style tools (e.g. system_info, list_dir) expect a bare value.
        action_str = f"{action}:{args}"
    elif args is None:
        action_str = action
    else:
        _emit({"ok": False, "error": "'args' must be an object or string"})
        return 0

    binding = gateway.binding_id_for_action(action)
    if binding is None:
        _emit({"ok": False, "error": f"unknown or unregistered tool: {action}"})
        return 0

    decision = gateway.policy.evaluate(
        action_str, Mode.GENERAL, Scope.PERSONAL, tool_binding_id=binding
    )
    if not decision.allowed:
        _emit({
            "ok": False,
            "error": f"denied by policy: {decision.reason}",
            "decision": {"allowed": decision.allowed, "reason": decision.reason},
        })
        return 0

    ts = int(time.time() * 1000)
    eid = f"dispatch:{ts}"
    rid = f"dispatch-req:{ts}"
    event = DecisionEvent.from_decision(
        decision, event_id=eid, request_id=rid, timestamp_ms=ts,
    )
    gateway.memory.append(event)

    try:
        result = gateway.execute(
            decision,
            decision_event_id=eid,
            result_event_id=f"{eid}:result",
            request_id=rid,
        )
    except Exception as exc:  # surfacing governance/gateway errors as JSON
        _emit({"ok": False, "error": f"execution error: {exc}", "tool": action})
        return 0

    _emit({
        "ok": bool(getattr(result, "success", False)),
        "tool": getattr(result, "tool", action),
        "output": getattr(result, "output", ""),
        "decision": {"allowed": decision.allowed, "reason": decision.reason},
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
