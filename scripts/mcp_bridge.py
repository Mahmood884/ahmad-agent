#!/usr/bin/env python3
"""MCP bridge: exposes agent-router.org tools to Hermes via stdio."""

import json
import subprocess
import sys

AGENT_ROUTER_URL = "https://agent-router.org/mcp"


def call_agent_router(method, params=None, req_id=1):
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    res = subprocess.run(
        ["curl", "-sL", "-X", "POST", AGENT_ROUTER_URL,
         "-H", "Content-Type: application/json",
         "-d", json.dumps(payload)],
        capture_output=True, text=True, timeout=30
    )
    return json.loads(res.stdout)


def main():
    # Initialize agent-router connection once
    call_agent_router("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "hermes", "version": "1.0"},
    }, req_id=0)

    # Notify Hermes we're ready
    ready = {"jsonrpc": "2.0", "id": None, "method": "notifications/initialized"}
    sys.stdout.write(json.dumps(ready) + "\n")
    sys.stdout.flush()

    # Read MCP requests from stdin
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        rid = req.get("id")
        method = req.get("method", "")

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0", "id": rid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "experimental": {},
                        "prompts": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                        "tools": {"listChanged": False},
                    },
                    "serverInfo": {"name": "AgentToAgent MCP Backend", "version": "1.30.0"},
                },
            }
        elif method == "tools/list":
            try:
                tools_data = call_agent_router("tools/list", req_id=rid)
                resp = {"jsonrpc": "2.0", "id": rid, "result": {"tools": tools_data.get("result", {}).get("tools", [])}}
            except Exception as e:
                resp = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": str(e)}}
        elif method == "tools/call":
            tool_name = req["params"]["name"]
            args = req["params"]["arguments"]
            try:
                call_data = call_agent_router("tools/call", {"name": tool_name, "arguments": args}, req_id=rid)
                resp = {"jsonrpc": "2.0", "id": rid, "result": call_data.get("result", {})}
            except Exception as e:
                resp = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": str(e)}}
        else:
            resp = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Unknown method: " + method}}

        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()