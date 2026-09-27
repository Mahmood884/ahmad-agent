import argparse
import json
import sys

from ahmad.core.identity import IDENTITY
from ahmad.core.runtime import AhmadRuntime
from ahmad.core.types import AgentRequest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ahmad")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("run", "status", "events", "providers", "tools", "policy"),
        default="run",
    )
    args = parser.parse_args(argv)
    runtime = AhmadRuntime()

    if args.command == "status":
        print(f"{IDENTITY.name} v{IDENTITY.version}")
        print(f"events: {len(runtime.memory.read_all())}")
        print(f"store: {runtime.memory.path}")
        return
    if args.command == "events":
        for event in runtime.memory.read_all():
            summary = {
                key: event[key]
                for key in (
                    "event_id", "request_id", "event_type", "action", "mode",
                    "allowed", "success", "tool", "decision_event_id",
                )
                if key in event
            }
            print(json.dumps(summary, sort_keys=True))
        return
    if args.command == "providers":
        print("claude-code: transport not configured")
        print("codex: transport not configured")
        print("hermes: transport not configured")
        return
    if args.command == "tools":
        for binding in runtime.gateway.registry.list():
            print(f"{binding.action}: {binding.metadata.name}@{binding.metadata.version}")
        return
    if args.command == "policy":
        print("default: deny")
        print("allowed demo rule: demo:mock / general / personal")
        return

    print(f"{IDENTITY.name} Agent v{IDENTITY.version}")
    print(IDENTITY.principle)
    prompt = "\nRequest: " if sys.stdin.isatty() else ""
    text = input(prompt).strip()
    if not text:
        print("No request supplied.")
        return

    response = runtime.handle(AgentRequest(text))

    print(f"Success: {response.success}")
    print(f"Tool: {response.tool}")
    print(f"Output: {response.output}")


if __name__ == "__main__":
    main()
