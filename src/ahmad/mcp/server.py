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
from ahmad.governance.policy import PolicyEngine
from ahmad.memory.store import MemoryStore
from ahmad.tools.read_file import ReadFileTool


# ─── Runtime (init once) ──────────────────────────────────────────────
_store = MemoryStore(Path("data/mcp-events.jsonl"))
_gateway = ExecutionGateway(memory=_store)
_base_policy = PolicyEngine()

# Register read_file with metadata + tool instance
_read_file_metadata = ToolMetadata(
    name="read_file",
    version="1.0",
    capabilities=("fs:read",),
    risk="low",
    implementation_id="read_file-v1",
)
_gateway.registry.register("read_file", _read_file_metadata, ReadFileTool())
_MCP_TOOL_NAMES = (
    "read_file",
    "list_dir",
    "system_info",
    "web_search",
    "web_scrape",
    "write_file",
    "scaffold_project",
    "venv_install",
    "theme_picker",
    "generate_ui",
    "component_lib",
    "memory_add",
    "memory_search",
    "memory_forget",
    "can_read",
    "modbus_read",
    "calibrate_sensor",
)
_TOOL_BINDINGS = {
    name: _gateway.binding_id_for_action(name)
    for name in _MCP_TOOL_NAMES
}
_ALLOWED_BINDINGS = frozenset(
    binding for binding in _TOOL_BINDINGS.values() if binding is not None
)


# Allow only registered MCP tools under their exact gateway binding fingerprints.
def _policy(
    action,
    mode,
    scope,
    *,
    source=None,
    tool_binding_id=None,
    network_approved=False,
):
    policy_decision = _base_policy.evaluate(
        action,
        mode,
        scope,
        source=source,
        tool_binding_id=tool_binding_id,
        network_approved=network_approved,
    )
    allowed = (
        scope is Scope.PERSONAL
        and tool_binding_id in _ALLOWED_BINDINGS
        and policy_decision.allowed
    )
    return Decision(
        action, mode, scope,
        allowed,
        (
            "mcp: explicit network approval"
            if allowed and action.startswith("component_lib:")
            else policy_decision.reason
        ),
        source=source,
        tool_binding_id=tool_binding_id,
        network_approved=network_approved,
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


def _dispatch_governed(
    req_id,
    action: str,
    tool_binding_id: str | None,
    *,
    execution_action: str | None = None,
    network_approved: bool = False,
) -> None:
    """Shared decision → gateway.execute path for any governed, read-only tool call."""
    decision = _gateway.policy.evaluate(
        action, Mode.GENERAL, Scope.PERSONAL,
        tool_binding_id=tool_binding_id,
        network_approved=network_approved,
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
            execution_action=execution_action,
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
    _dispatch_governed(req_id, f"read_file:{path}", _TOOL_BINDINGS["read_file"])


def _call_list_dir(req_id, arguments: dict) -> None:
    path = arguments.get("path") or ""
    action = f"list_dir:{path}" if path else "list_dir"
    _dispatch_governed(req_id, action, _TOOL_BINDINGS["list_dir"])


def _call_system_info(req_id, arguments: dict) -> None:
    section = arguments.get("section") or ""
    action = f"system_info:{section}" if section else "system_info"
    _dispatch_governed(req_id, action, _TOOL_BINDINGS["system_info"])


def _call_registered_tool(req_id, name: str, arguments: dict) -> None:
    try:
        if name == "web_search":
            action = f"web_search:{arguments.get('query', '')}"
        elif name == "web_scrape":
            action = f"web_scrape:{arguments.get('url', '')}"
        elif name == "write_file":
            action = (
                f"write_file:{arguments.get('path', '')}"
                f"|mode={arguments.get('mode', '')}|{arguments.get('content', '')}"
            )
        elif name == "scaffold_project":
            action = (
                f"scaffold_project:name={arguments.get('name', '')}"
                f"|type={arguments.get('type', 'python-cli')}"
            )
        elif name == "venv_install":
            action = (
                f"venv_install:packages={arguments.get('packages', '')}"
                f"|cwd={arguments.get('cwd', '')}"
            )
        else:
            action = f"{name}:{json.dumps(arguments)}"
        execution_action = None
        network_approved = name == "component_lib" and arguments.get("allow_network") is True
        if name in {"memory_add", "memory_search", "memory_forget"}:
            execution_action = action
            action = name
        _dispatch_governed(
            req_id,
            action,
            _TOOL_BINDINGS[name],
            execution_action=execution_action,
            network_approved=network_approved,
        )
    except (KeyError, TypeError, ValueError) as exc:
        _err(req_id, f"invalid arguments for {name}: {exc}")


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
                        "description": "List directory entries (governed, rooted at $HOME).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                        },
                    },
                    {
                        "name": "system_info",
                        "description": "Read-only system info (cpu, memory, disk, os).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"section": {"type": "string"}},
                        },
                    },
                    {
                        "name": "web_search",
                        "description": "Search the public web.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    },
                    {
                        "name": "web_scrape",
                        "description": "Fetch text from an allowed public website.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"url": {"type": "string", "format": "uri"}},
                            "required": ["url"],
                        },
                    },
                    {
                        "name": "write_file",
                        "description": "Write a file under the workspace root.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "mode": {"type": "string", "enum": ["create", "overwrite"]},
                                "content": {"type": "string"},
                            },
                            "required": ["path", "mode", "content"],
                        },
                    },
                    {
                        "name": "scaffold_project",
                        "description": "Create a Python CLI project under the workspace root.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string", "enum": ["python-cli"]},
                            },
                            "required": ["name"],
                        },
                    },
                    {
                        "name": "venv_install",
                        "description": "Install packages inside an existing workspace .venv.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "packages": {"type": "string"},
                                "cwd": {"type": "string"},
                            },
                            "required": ["packages", "cwd"],
                        },
                    },
                    {
                        "name": "theme_picker",
                        "description": "Choose an accessible built-in color theme and report contrast ratios.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "enum": ["ocean", "forest", "berry"],
                                }
                            },
                            "required": ["name"],
                        },
                    },
                    {
                        "name": "generate_ui",
                        "description": "Generate a local React, Tailwind CSS, and shadcn-ready project.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                                "theme": {
                                    "type": "string",
                                    "enum": ["ocean", "forest", "berry"],
                                },
                            },
                            "required": ["name", "description"],
                        },
                    },
                    {
                        "name": "component_lib",
                        "description": "Use the official shadcn CLI to add an allowlisted component to a generated local UI project. This downloads code; set allow_network=true only after explicitly approving the download.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "project_dir": {"type": "string"},
                                "component": {"type": "string"},
                                "allow_network": {"type": "boolean"},
                            },
                            "required": ["project_dir", "component", "allow_network"],
                        },
                    },
                    {
                        "name": "memory_add",
                        "description": "Save a note to this operating-system user's local SQLite memory.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"content": {"type": "string"}},
                            "required": ["content"],
                        },
                    },
                    {
                        "name": "memory_search",
                        "description": "Search this operating-system user's local memory using full-text matching.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                            },
                            "required": ["query"],
                        },
                    },
                    {
                        "name": "memory_forget",
                        "description": "Permanently delete one of this operating-system user's local memories by ID.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"id": {"type": "integer", "minimum": 1}},
                            "required": ["id"],
                        },
                    },
                    {
                        "name": "can_read",
                        "description": "Read a bounded number of frames from a Linux SocketCAN interface; never sends frames.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "interface": {"type": "string", "enum": ["socketcan"]},
                                "channel": {"type": "string", "pattern": "^can[0-9]+$"},
                                "max_frames": {"type": "integer", "minimum": 1, "maximum": 100},
                                "timeout": {"type": "number", "exclusiveMinimum": 0, "maximum": 10},
                            },
                        },
                    },
                    {
                        "name": "modbus_read",
                        "description": "Read holding registers from a private or loopback IP. No write function codes are exposed.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "host": {
                                    "type": "string",
                                    "description": "Private/loopback IP literal; hostnames/public addresses are denied.",
                                },
                                "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                                "unit_id": {"type": "integer", "minimum": 1, "maximum": 247},
                                "address": {"type": "integer", "minimum": 0, "maximum": 65535},
                                "count": {"type": "integer", "minimum": 1, "maximum": 125},
                            },
                            "required": ["host", "unit_id", "address"],
                        },
                    },
                    {
                        "name": "calibrate_sensor",
                        "description": "Fit an offline linear or quadratic curve to supplied x/y points; does not access or change sensor hardware.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 100},
                                "y": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 100},
                                "model": {"type": "string", "enum": ["linear", "quadratic"]},
                            },
                            "required": ["x", "y"],
                        },
                    },
                ]
            },
        })
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            send_response({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": "Tool arguments must be an object"},
            })
            return
        if name == "ping":
            _call_ping(req_id)
        elif name == "read_file":
            _call_read_file(req_id, args)
        elif name == "list_dir":
            _call_list_dir(req_id, args)
        elif name == "system_info":
            _call_system_info(req_id, args)
        elif name in _TOOL_BINDINGS:
            _call_registered_tool(req_id, name, args)
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
