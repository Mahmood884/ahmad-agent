"""MCP Server — ahmad-agent tools via stdio transport.

Exposes governed tools over Model Context Protocol (stdio, JSON-RPC lines).
Every tool call is routed through the ExecutionGateway with a DecisionEvent.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from ahmad.core.events import DecisionEvent
from ahmad.core.types import Decision, Mode, Scope
from ahmad.execution.gateway import ExecutionGateway
from ahmad.execution.registry import ToolMetadata
from ahmad.memory.store import MemoryStore
from ahmad.tools.read_file import ReadFileTool


# ─── Runtime (init once) ──────────────────────────────────────────────
_store = MemoryStore(Path("data/mcp-events.jsonl"))
_gateway = ExecutionGateway(memory=_store)

# Register read_file with metadata + tool instance
_read_file_metadata = ToolMetadata(
    name="read_file",
    version="1.0",
    capabilities=("fs:read",),
    risk="low",
    implementation_id="read_file-v1",
)
_gateway.registry.register("read_file", _read_file_metadata, ReadFileTool())

# Read-only policy: allow read_file under $HOME with matching binding
_READ_BINDING = _gateway.binding_id_for_action("read_file")


def _policy(action, mode, scope, *, source=None, tool_binding_id=None):
    allowed = (
        action.startswith("read_file:")
        and scope is Scope.PERSONAL
        and tool_binding_id == _READ_BINDING
    )
    return Decision(
        action, mode, scope,
        allowed,
        "mcp: read_file approval" if allowed else "default deny",
        source=source,
        tool_binding_id=tool_binding_id,
    )


_gateway.policy.evaluate = _policy


# ─── JSON-RPC helpers ────────────────────────────────────────────────
def send_response(response: dict) -> None:
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def _ok(req_id, text: str) -> None:
    send_response({
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"content": [{"type": "text", "text": text}]},
    })


def _err(req_id, text: str) -> None:
    send_response({
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "content": [{"type": "text", "text": text}],
            "isError": True,
        },
    })


# ─── Tool handlers ───────────────────────────────────────────────────
def _call_ping(req_id) -> None:
    _ok(req_id, "PONG from ahmad-agent")


def _call_read_file(req_id, arguments: dict) -> None:
    path = arguments.get("path")
    if not path:
        _err(req_id, "missing path")
        return

    action = f"read_file:{path}"
    decision = _gateway.policy.evaluate(
        action, Mode.GENERAL, Scope.PERSONAL,
        tool_binding_id=_READ_BINDING,
    )

    # Create a unique event pair
    ts = int(time.time() * 1000)
    eid = f"mcp:{req_id}:{ts}"
    rid = f"mcp-req:{req_id}:{ts}"

    event = DecisionEvent.from_decision(
        decision, event_id=eid, request_id=rid, timestamp_ms=ts,
    )
    _store.append(event)

    try:
        result = _gateway.execute(
            decision,
            decision_event_id=eid,
            result_event_id=f"{eid}:result",
            request_id=rid,
        )
    except Exception as exc:  # pragma: no cover — defensive
        _err(req_id, f"gateway error: {exc}")
        return

    if result.success:
        _ok(req_id, result.output)
    else:
        _err(req_id, result.output)


# ─── Request dispatcher ──────────────────────────────────────────────
def handle_request(request: dict) -> None:
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "ahmad-agent", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            },
        })
    elif method == "tools/list":
        send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "ping",
                        "description": "Test tool — returns pong",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "read_file",
                        "description": "Read a file from disk (governed, rooted at $HOME).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Absolute or relative path to the file",
                                }
                            },
                            "required": ["path"],
                        },
                    },
                ]
            },
        })
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "ping":
            _call_ping(req_id)
        elif name == "read_file":
            _call_read_file(req_id, args)
        else:
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {name}"},
            })
    elif method == "notifications/initialized":
        pass
    else:
        send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        })


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            handle_request(request)
        except Exception as e:
            sys.stderr.write(f"Error handling {request.get('method')}: {e}\n")


if __name__ == "__main__":
    main()
