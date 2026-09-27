from pathlib import Path

from ahmad.core.events import DecisionEvent
from ahmad.core.types import Mode, Scope
from ahmad.execution.gateway import ExecutionGateway
from ahmad.governance.policy import MOCK_TOOL_BINDING_ID, PolicyEngine
from ahmad.memory.store import MemoryStore


def test_full_slice_allowed(tmp_path: Path):
    memory = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(memory=memory)
    decision = PolicyEngine().evaluate(
        "demo:mock", Mode.GENERAL, Scope.PERSONAL,
        tool_binding_id=MOCK_TOOL_BINDING_ID,
    )
    memory.append(DecisionEvent.from_decision(
        decision, event_id="allowed-001", request_id="request-allowed",
        timestamp_ms=1000,
    ))

    result = gateway.execute(
        decision, decision_event_id="allowed-001",
        result_event_id="allowed-001:result", request_id="request-allowed",
    )

    assert result.success is True

    events = memory.read_all()
    assert len(events) == 2
    assert events[0]["event_type"] == "decision" and events[0]["allowed"] is True
    assert events[1]["event_type"] == "result" and events[1]["success"] is True
    assert events[1]["decision_event_id"] == events[0]["event_id"]


def test_full_slice_denied(tmp_path: Path):
    memory = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(memory=memory)

    decision = PolicyEngine().evaluate("do something", Mode.GENERAL, Scope.AUTHORIZED)
    memory.append(DecisionEvent.from_decision(
        decision, event_id="denied-001", request_id="request-denied", timestamp_ms=2000
    ))
    result = gateway.execute(
        decision, decision_event_id="denied-001",
        result_event_id="denied-001:result", request_id="request-denied",
    )

    assert result.success is False
    assert result.tool == "none"
    assert result.output == "EXECUTION_DENIED"

    events = memory.read_all()
    assert len(events) == 2
    assert events[0]["event_type"] == "decision" and events[0]["allowed"] is False
    assert events[1]["event_type"] == "result" and events[1]["success"] is False
    assert events[1]["decision_event_id"] == events[0]["event_id"]
