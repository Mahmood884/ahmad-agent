from ahmad.core.events import DecisionEvent
from ahmad.core.identity import IDENTITY
from ahmad.core.types import Mode, Scope
from ahmad.execution.gateway import ExecutionGateway
from ahmad.governance.policy import PolicyEngine
from ahmad.memory.store import MemoryStore
from ahmad.orchestration.router import Router


def test_identity():
    assert IDENTITY.name == "Ahmad"


def test_router():
    router = Router()
    assert router.route("research GitHub tools").value == "research"


def test_gateway_default_deny(tmp_path):
    memory = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(memory=memory)
    decision = PolicyEngine().evaluate("test action", Mode.GENERAL, Scope.PERSONAL)
    memory.append(DecisionEvent.from_decision(
        decision, event_id="decision-001", request_id="request-001"
    ))
    result = gateway.execute(
        decision,
        decision_event_id="decision-001",
        result_event_id="decision-001:result",
        request_id="request-001",
    )

    assert result.success is False
    assert result.tool == "none"
    assert result.output == "EXECUTION_DENIED"
