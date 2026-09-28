# Ahmad Agent

> Local-first governed AI agent runtime.
> Agent intelligence must never equal system authority.

---

## What it is

Ahmad is a **governance layer** for AI agents. It sits between an agent's
intelligence (LLM) and any side effect (tool, file, shell, API). Every
action passes through a deterministic policy engine, an execution gateway,
and an append-only event log.

This is not a chatbot. It is infrastructure.

---

## Core principle

    Agent intelligence  !=  system authority

The LLM may **propose**. Only the gateway may **execute**, and only after
policy approval, binding verification, and durable event recording.

---

## Architecture

    User (CLI / MCP / HTTP)
        |
    Agent Brain (Hermes / Claude / local LLM)
        |
    Provider Adapter (subprocess, HTTP, etc.)
        |
    Orchestration (runtime)
        |
    Governance (PolicyEngine, Trust, DecisionEvent)
        |
    Execution Gateway (admission, binding, attempt lifecycle)
        |
    Tools (read_file, system_info, ...)

Every decision produces:
- DecisionEvent (allowed/denied, reason, binding)
- AttemptCreatedEvent / AttemptStartedEvent (dispatch)
- ResultEvent (success/failure, output)
- AttemptAmbiguousEvent (when effect status is unknown)

All events are **append-only** and replayable.

---

## Components

| Layer | Purpose | Path |
|---|---|---|
| Identity | Agent name, version, principle | src/ahmad/core/identity.py |
| Runtime | Orchestration, provider requests | src/ahmad/core/runtime.py |
| Types | Decisions, Modes, Scopes, Effects | src/ahmad/core/types.py |
| Events | DecisionEvent, ResultEvent | src/ahmad/core/events.py |
| Attempts | Attempt lifecycle events | src/ahmad/core/attempts.py |
| Resolutions | Ambiguity resolution | src/ahmad/core/resolutions.py |
| Policy | PolicyEngine, binding-aware rules | src/ahmad/governance/policy.py |
| Gateway | Final execution boundary | src/ahmad/execution/gateway.py |
| Registry | Tool + capability metadata | src/ahmad/execution/registry.py |
| Store | JSONL + SQLite WAL event stores | src/ahmad/memory/ |
| Projections | Rebuildable state from events | src/ahmad/memory/attempt_projection.py |
| Providers | Hermes, Claude Code, Codex adapters | src/ahmad/providers/ |
| Tools | Governed tools (read_file) | src/ahmad/tools/ |
| MCP | Model Context Protocol server | src/ahmad/mcp/server.py |
| CLI | Interactive REPL | src/ahmad/__main__.py |

---

## Installation

    git clone <repo> ahmad-agent
    cd ahmad-agent
    python3 -m venv .venv
    source .venv/bin/activate
    pip install pytest pyyaml
    pip install -e .

Requires Python 3.11+.

---

## Usage

### CLI REPL

    python -m ahmad
    python -m ahmad --provider hermes
    python -m ahmad --provider none

Commands:
    /help              Show help
    /events [N]        Show last N events
    /tools             List registered tools
    /providers         List registered providers
    /status            Runtime status
    /clear             Clear screen
    exit / quit / :q   Exit

### MCP Server (stdio)

    python -m ahmad.mcp.server

Hermes integration:

    hermes mcp add ahmad-poc --command python --args -m ahmad.mcp.server
    hermes mcp test ahmad-poc

Exposed tools:
- ping         - connectivity test
- read_file    - governed file read (rooted at $HOME, max 1 MB)

Every MCP tool call is routed through ExecutionGateway with a fresh DecisionEvent.

---

## Providers

| Provider | Transport | Status |
|---|---|---|
| Hermes | SubprocessTransport -> hermes chat -q ... -Q | Real |
| Claude Code | (not configured) | Pending |
| Codex | (not configured) | Pending |

Providers must be explicitly registered. Selection grants no authority.

---

## Tests

    pytest tests/ -v

96 tests covering governance, event sourcing, attempt lifecycle,
provider adapters, governed tools, CLI, MCP server, concurrency,
and corrupted JSONL recovery.

---

## Status

v0.1.0 - Foundation + First Tool + MCP Bridge
