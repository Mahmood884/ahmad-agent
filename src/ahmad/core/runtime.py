from pathlib import Path

from ahmad.core.events import DecisionEvent
from ahmad.core.types import AgentRequest
from ahmad.execution.gateway import ExecutionGateway
from ahmad.execution.mock_tool import ToolResult
from ahmad.governance.policy import PolicyEngine
from ahmad.memory.store import MemoryStore
from ahmad.orchestration.router import Router


class AhmadRuntime:
    def __init__(
        self,
        *,
        event_store: MemoryStore | None = None,
    ) -> None:
        self.router = Router()
        self.policy = PolicyEngine()
        self.gateway = ExecutionGateway()
        self.memory = event_store or MemoryStore(
            Path("data/events.jsonl")
        )

    def handle(
        self,
        request: AgentRequest,
        *,
        event_id: str,
    ) -> ToolResult:
        mode = self.router.route(request.text)

        decision = self.policy.evaluate(
            action=request.text,
            mode=mode,
            scope=request.scope,
        )

        decision_event = DecisionEvent.from_decision(
            decision,
            event_id=event_id,
        )

        # Persist the governance decision before execution.
        self.memory.append(decision_event)

        return self.gateway.execute(decision)
