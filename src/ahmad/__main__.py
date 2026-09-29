"""Ahmed Agent — interactive REPL.

Usage:
    python -m ahmad
    python -m ahmad --provider hermes
    python -m ahmad --no-provider
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from ahmad.core.identity import IDENTITY
from ahmad.core.runtime import AhmadRuntime
from ahmad.memory.store import MemoryStore


BANNER = """
╔══════════════════════════════════════════════╗
║   Ahmed Agent — Interactive REPL             ║
║   Governed multi-provider agent runtime      ║
╚══════════════════════════════════════════════╝
"""

HELP = """
Commands:
  /help              Show this help
  /events [N]        Show last N events (default: 10)
  /tools             List registered tools
  /providers         List available providers
  /status            Show runtime status
  /reset             Clear conversation history (this session)
  /clear             Clear screen
  exit, quit, :q     Exit

Anything else is sent to the provider as a prompt.
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ahmad",
        description="Ahmed Agent — interactive REPL",
    )
    parser.add_argument(
        "--provider", "-p",
        default="hermes",
        help="Provider to use (default: hermes). Use 'none' for no provider.",
    )
    parser.add_argument(
        "--events",
        type=int,
        default=10,
        help="Number of events to show in /events (default: 10).",
    )
    parser.add_argument(
        "--store",
        default="data/events.jsonl",
        help="Path to the event store (default: data/events.jsonl).",
    )
    return parser


def _register_providers(runtime: AhmadRuntime, name: str) -> None:
    """Register the requested provider if available."""
    if name == "none":
        print("  Providers: disabled (no provider registered)")
        return

    if name == "hermes":
        if shutil.which("hermes") is None:
            print("  ⚠ hermes CLI not found — running in no-provider mode")
            return
        from ahmad.providers.hermes import HermesProvider
        runtime.providers.register(HermesProvider())
        print("  Provider: hermes (registered)")
        return

    # Unknown provider name — attempt registry lookup, else fail soft
    print(f"  ⚠ unknown provider: {name} — running in no-provider mode")


def _cmd_help() -> None:
    print(HELP)


def _cmd_events(runtime: AhmadRuntime, n: int) -> None:
    events = runtime.memory.read_all()
    tail = events[-n:]
    if not tail:
        print("  (no events yet)")
        return
    for ev in tail:
        kind = ev.get("event_type", "?")
        eid = ev.get("event_id", "?")
        action = ev.get("action", "")
        extra = ""
        if kind == "decision":
            extra = f" allowed={ev.get('allowed')}"
        elif kind == "result":
            extra = f" success={ev.get('success')} tool={ev.get('tool')}"
        print(f"  [{kind}] {eid} {action}{extra}")


def _cmd_tools(runtime: AhmadRuntime) -> None:
    tools = runtime.gateway.registry.list()
    if not tools:
        print("  (no tools registered)")
        return
    for binding in tools:
        meta = binding.metadata
        print(f"  {binding.action}: {meta.name}@{meta.version}")


def _cmd_providers(runtime: AhmadRuntime) -> None:
    providers = runtime.providers.list()
    if not providers:
        print("  (no providers registered)")
        return
    for p in providers:
        print(f"  {p.name}: {type(p).__name__}")


def _cmd_status(runtime: AhmadRuntime) -> None:
    print(f"  Agent: {IDENTITY.name} v{IDENTITY.version}")
    print(f"  Store: {runtime.memory.path}")
    print(f"  Events: {len(runtime.memory.read_all())}")
    print(f"  Providers: {len(runtime.providers.list())}")
    print(f"  Tools: {len(runtime.gateway.registry.list())}")
    print(f"  Conversation turns: {len(runtime._get_conversation('default'))}")


def repl(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    print(BANNER)

    store = MemoryStore(Path(args.store))
    runtime = AhmadRuntime(memory=store)

    _register_providers(runtime, args.provider)
    print()

    while True:
        try:
            line = input("ahmad> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        if line in ("exit", "quit", ":q"):
            break

        if line == "/help":
            _cmd_help()
            continue
        if line == "/events":
            _cmd_events(runtime, args.events)
            continue
        if line.startswith("/events "):
            try:
                n = int(line.split()[1])
            except (IndexError, ValueError):
                n = args.events
            _cmd_events(runtime, n)
            continue
        if line == "/tools":
            _cmd_tools(runtime)
            continue
        if line == "/providers":
            _cmd_providers(runtime)
            continue
        if line == "/status":
            _cmd_status(runtime)
            continue
        if line == "/reset":
            runtime.reset_conversation()
            print("  conversation cleared (in-memory)")
            continue
        if line == "/clear":
            print("\033[2J\033[H", end="")
            continue

        # Prompt → provider
        if not runtime.providers.list():
            print("  ⚠ no provider registered — use --provider hermes")
            continue

        try:
            print()
            print("  ", end="", flush=True)
            for chunk in runtime.stream_provider_request(args.provider, line):
                print(chunk, end="", flush=True)
            print()
            outcome = runtime.last_stream_outcome
            if outcome is not None and outcome.tool_results:
                for tr in outcome.tool_results:
                    marker = "✅" if tr.success else "❌"
                    print(f"  {marker} tool={tr.tool} output={tr.output[:120]}")
                print()
        except Exception as exc:
            print(f"  ❌ error: {exc}")

    print("\nBye.\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    return repl(argv)


if __name__ == "__main__":
    sys.exit(main())
