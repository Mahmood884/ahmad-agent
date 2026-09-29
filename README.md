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
- list_dir, system_info - bounded local inspection tools
- web_search, web_scrape - public web lookup (scraping is domain allowlisted)
- write_file, scaffold_project, venv_install - workspace-scoped project tools
- theme_picker - curated palettes with WCAG AA contrast checks
- generate_ui - local React, Tailwind CSS, and shadcn-ready project generator
- component_lib - invokes the official shadcn CLI for allowlisted components;
  requires explicit `allow_network: true` approval before accessing the network
- memory_add, memory_search, memory_forget - local SQLite full-text memory,
  partitioned by operating-system user and stored under that user's home directory
- can_read - bounded receive-only reads from a Linux SocketCAN interface
- modbus_read - bounded holding-register reads from private/loopback IP addresses
- calibrate_sensor - offline SciPy linear/quadratic fitting from supplied points

`generate_ui` accepts a project slug, a short description, and one of the
`ocean`, `forest`, or `berry` themes. It creates a new project under the
workspace root and refuses to overwrite existing paths. Install its declared
Node dependencies with `npm install` and start it with `npm run dev`.
`component_lib` only operates inside a project created by `generate_ui`, and
accepts a fixed component allowlist to avoid passing arbitrary CLI arguments.
It is denied by policy unless `allow_network: true` is explicitly supplied
after approving the component download.
Memory tools do not accept a caller-supplied user ID: the MCP server derives
the partition from its operating-system account. Each account gets a separate
`~/.local/share/ahmad-agent/memories.sqlite3` database with owner-only file
permissions. Search is lexical full-text search, not semantic/vector search;
`memory_forget` deletes one memory by its ID. Memory content and search results
are redacted from the append-only governance event log; the log records only
the tool name and a process-keyed input digest.
Memory deletion enables SQLite `secure_delete`, vacuums the database, and
checkpoints/truncates WAL files. These measures are not encryption and cannot
protect a powered-off/copied storage device or guarantee erasure from
filesystem snapshots and backups. Full database encryption is deferred to
v0.3.0 so it can be designed together with key storage, rotation, and recovery.

CAN and Modbus tools do not transmit CAN frames or expose Modbus write functions.
Modbus requests require a literal private/loopback IP address, a unit ID,
register address, and a bounded read count. `calibrate_sensor` only fits the
provided `x`/`y` data; it never reads or changes a physical sensor. Install
these optional integrations in the project environment with:

    .venv/bin/pip install -e ".[industrial]"

The extra includes `python-can`, `pymodbus`, and `scipy`. `pyproject.toml` is
the sole dependency source of truth; do not maintain a `requirements.txt`
generated by `pip freeze`.

### Known limitations

`can_read` accepts Linux SocketCAN channel names matching `can` followed by
digits (such as `can0`); `vcan0` is rejected. Each call is limited to 100
frames and 10 seconds, and the tool enforces a minimum one-second interval
between calls on the same `CanReadTool` instance. There is no separate
production-mode guard.
`modbus_read` rejects hostnames and checks that a literal IP is private or
loopback before connecting. Its configured client timeout is 3 seconds per
socket operation; library retries may extend total wall-clock time.
`calibrate_sensor` requires at least two points for a linear fit and three for
a quadratic fit, with the same minimum number of distinct x values. Duplicate
samples are accepted if enough distinct x values remain. It does not detect
poor conditioning or outliers.

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
