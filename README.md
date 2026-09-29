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
`memory_forget` deletes one memory by its ID. Memory content and search results are redacted from the append-only governance
event log; the log records only the tool name and an HMAC input digest. The
digest key is stored at `~/.config/ahmad/digest.key` with owner-only (`0600`)
permissions so identical memory inputs retain stable digests across gateway
restarts. SQLite event and local-memory databases use SQLCipher and a separate
key at `~/.config/ahmad/encryption.key` (also mode `0600`). Losing that key
makes the encrypted databases unrecoverable; back it up securely.
This encryption covers the SQLite event and memory stores only. Conversation
turn history is currently persisted as plaintext JSONL under
`data/conversations/`; keep that directory private and do not treat SQLCipher as
protection for those transcripts. The CLI's default event store is JSONL too.

To convert an existing plaintext SQLite database, stop Ahmad and every process
using the database, then run:

    ahmad-sqlite-migrate /path/to/database.db --confirm-application-stopped

The migrator verifies schema and row counts before replacing the database and
preserves a mode-`0600` plaintext backup at `DATABASE.plaintext.bak`. Protect
that backup as sensitive data and apply your retention/deletion policy to it.
SQLCipher protects database files at rest; it does not by itself establish
GDPR compliance or erase plaintext backups, exports, filesystem snapshots, or
copies held elsewhere. `memory_forget` additionally enables SQLite
`secure_delete`, vacuums, and checkpoints/truncates WAL files.

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

## Governance dashboard

Run the read-only local dashboard with:

    ahmad-dashboard

It reads the CLI's default `data/events.jsonl` store and serves the newest 100
events at `http://127.0.0.1:8765` (JSON at `/api/events`). Use `--store PATH`
to select another JSONL event store and `--port PORT` to change the local
port. It binds only to a loopback IP and rejects non-local Host headers. It
does not provide authentication; event data remains accessible to local
processes and browser sessions on the machine, so protect the event store and
close the dashboard when it is not needed.

## Multi-agent coordination

The bounded coordinator lets registered providers exchange analysis without
granting agents execution authority:

    from ahmad.agents.coordinator import AgentSpec, MultiAgentCoordinator

    coordinator = MultiAgentCoordinator(runtime)
    result = coordinator.run(
        "Review this design",
        [
            AgentSpec("planner", "planner", "hermes"),
            AgentSpec("critic", "critic", "hermes"),
        ],
        rounds=2,
    )
    print(result.transcript)

Each agent ID must be unique and each provider must already be registered on
the runtime. Rounds, turns, transcript length, and per-turn output are bounded.
Provider-proposed actions are counted for reporting but never executed; any
real side effect must still be separately submitted through the governed
runtime.

## Conversations, streaming, and cost

Provider conversations retain bounded turns by conversation ID. The REPL
streams text as the provider emits it when the configured transport supports
streaming; other provider adapters may fall back to a single completed chunk.
`AhmadRuntime.stream_provider_request()` exposes the same interface to callers.
Final proposed actions continue through the normal governance gateway.

Provider-call records are appended to `data/provider_costs.jsonl` without
prompts or generated text. Usage and cost are marked as provider-reported when
metadata supplies them. When token usage is missing, configured per-provider
rates can produce a clearly marked character-based estimate; otherwise cost
is recorded as unknown. Rates are passed with `provider_rates` when creating
`AhmadRuntime`; estimates are not billing statements.
Conversation transcripts contain the prompt and response and are not encrypted
by this feature; protect and delete them according to your data-retention
requirements. The REPL's `/reset` clears the active in-memory context; it does
not erase the corresponding persisted transcript file.

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

Tests cover governance, event sourcing, attempt lifecycle, provider adapters,
governed tools, CLI, MCP server, concurrency, encrypted SQLite/migration,
streaming, cost accounting, and corrupted JSONL recovery.

---

## Status

v0.1.0 - Foundation + First Tool + MCP Bridge
