from ahmad.core.identity import IDENTITY
from ahmad.orchestration.router import Router
from ahmad.execution.gateway import ExecutionGateway


def main() -> None:
    router = Router()
    gateway = ExecutionGateway()

    print(f"{IDENTITY.name} Agent v{IDENTITY.version}")
    print(IDENTITY.principle)

    request = input("\nRequest: ").strip()

    if not request:
        print("No request supplied.")
        return

    mode = router.route(request)

    print(f"Mode: {mode.value}")

    result = gateway.request(request)

    print(f"Allowed: {result['allowed']}")
    print(f"Executed: {result['executed']}")
    print(f"Reason: {result['reason']}")


if __name__ == "__main__":
    main()
