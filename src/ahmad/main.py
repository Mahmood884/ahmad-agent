from ahmad.core.identity import IDENTITY
from ahmad.core.runtime import AhmadRuntime
from ahmad.core.types import AgentRequest


def main() -> None:
    runtime = AhmadRuntime()

    print(f"{IDENTITY.name} Agent v{IDENTITY.version}")
    print(IDENTITY.principle)

    request = input("\nRequest: ").strip()

    if not request:
        print("No request supplied.")
        return

    result = runtime.handle(
        AgentRequest(request),
        event_id="cli-001",
    )

    print(f"Success: {result.success}")
    print(f"Tool: {result.tool}")
    print(f"Output: {result.output}")


if __name__ == "__main__":
    main()
