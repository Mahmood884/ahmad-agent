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
from ahmad.tools.list_dir import ListDirTool
from ahmad.tools.read_file import ReadFileTool
from ahmad.tools.system_info import SystemInfoTool


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
_READ_BINDING = _gateway.binding_id_for_action("read_file")

# Register list_dir
_list_dir_metadata = ToolMetadata(
    name="list_dir",
    version="1.0",
    capabilities=("fs:list",),
    risk="low",
    implementation_id="list_dir-v1",
)

# Register system_info
_system_info_metadata = ToolMetadata(
    name="system_info",
    version="1.0",
    capabilities=("system:read",),
    risk="low",
    implementation_id="system_info-v1",
)


# Read-only policy: allow each tool only under its own exact binding fingerprint
def _policy(action, mode, scope, *, source=None, tool_binding_id=None):
    allowed = scope is Scope.PERSONAL and (
        (action.startswith("read_file:") and tool_binding_id == _READ_BINDING)
        or (
            (action == "list_dir" or action.startswith("list_dir:"))
            and tool_binding_id == _LIST_DIR_BINDING
        )
        or (
            (action == "system_info" or action.startswith("system_info:"))
            and tool_binding_id == _SYSTEM_INFO_BINDING
        )
    )
    return Decision(
        action, mode, scope,
        allowed,
        "mcp: read-only tool approval" if allowed else "default deny",
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


def _dispatch_governed(req_id, action: str, tool_binding_id: str | None) -> None:
    """Shared decision → gateway.execute path for any governed, read-only tool call."""
    decision = _gateway.policy.evaluate(
        action, Mode.GENERAL, Scope.PERSONAL,
        tool_binding_id=tool_binding_id,
    )

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


# ─── Tool handlers ───────────────────────────────────────────────────
def _call_ping(req_id) -> None:
    _ok(req_id, "PONG from ahmad-agent")


def _call_read_file(req_id, arguments: dict) -> None:
    path = arguments.get("path")
    if not path:
        _err(req_id, "missing path")
        return
    _dispatch_governed(req_id, f"read_file:{path}", _READ_BINDING)


def _call_list_dir(req_id, arguments: dict) -> None:
    path = arguments.get("path") or ""
    action = f"list_dir:{path}" if path else "list_dir"
    _dispatch_governed(req_id, action, _LIST_DIR_BINDING)


def _call_system_info(req_id, arguments: dict) -> None:
    section = arguments.get("section") or ""
    action = f"system_info:{section}" if section else "system_info"
    _dispatch_governed(req_id, action, _SYSTEM_INFO_BINDING)


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
                    {
                        "name": "list_dir",
                        "description": "List a directory's entries (governed, rooted at $HOME).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Directory path (default: $HOME)",
                                }
                            },
                        },
                    },
                    {
                        "name": "system_info",
                        "description": "Read-only system info (cpu, memory, disk, os).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "section": {
                                    "type": "string",
                                    "description": "cpu | memory | disk | os (default: all)",
                                }
                            },
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
        elif name == "list_dir":
            _call_list_dir(req_id, args)
        elif name == "system_info":
            _call_system_info(req_id, args)
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
