# Ahmad Agent

Local-first governed AI agent runtime.

## Architecture

Intelligence
→ Orchestration
→ Governance
→ Execution Gateway
→ System

## Core Principle

Agent intelligence must never equal system authority.

## Current Version

0.1.0 — Foundation

## Current Components

- Agent identity
- Request router
- Governance boundary
- Default-deny execution gateway
- Memory interface
- Skills directory
- Tools directory
- Agents directory
- JSONL and SQLite WAL event stores
- Rebuildable in-memory event projections
- Capability and tool metadata registries (registration is not authorization)
- Provider adapter contracts for Claude Code, Codex, and Hermes (transports are not configured)

## CLI

```text
ahmad run       # interactive request
ahmad status    # store and event count
ahmad events    # event metadata; tool output is omitted
ahmad providers # configured provider transports
ahmad tools     # registered tool metadata
ahmad policy    # current default-deny policy summary
```

The default event store is `data/ahmad.db` using SQLite WAL. `MemoryStore` remains
available for JSONL workflows and tests. Events are the source of truth;
projections are disposable views rebuilt from event records. Logs omit request
text and tool output to reduce accidental secret exposure.

## Provider boundary

Claude Code, Codex, and Hermes adapters are transport contracts only. They have
no built-in CLI, subprocess, filesystem, network, or tool access. A registered
provider may return text, a plan, metadata, and proposed actions. Ahmad routes
each proposal through PolicyEngine, persists its DecisionEvent, and then invokes
ExecutionGateway, which rechecks policy before calling a registered tool.
Provider registration and selection do not authorize actions. No provider is
registered or executed automatically; tests use injected in-memory transports.

## Planned

- Claude Code integration
- MCP
- Agent Skills
- Sub-agents
- Event-sourced memory
- Policy Registry
- Signed policies
- Execution adapters
