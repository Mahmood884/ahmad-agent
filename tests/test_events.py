import json

from ahmad.core.events import DecisionEvent, EventType
from ahmad.core.types import Mode, Scope
from ahmad.governance.policy import PolicyEngine
from ahmad.governance.policy import MOCK_TOOL_BINDING_ID


def test_decision_event_from_decision():
    policy = PolicyEngine()

    decision = policy.evaluate(
        action="demo:mock",
        mode=Mode.GENERAL,
        scope=Scope.PERSONAL,
        tool_binding_id=MOCK_TOOL_BINDING_ID,
    )

    event = DecisionEvent.from_decision(
        decision,
        event_id="event-001",
        request_id="request-001",
        timestamp_ms=1234567890,
    )

    assert event.event_id == "event-001"
    assert event.timestamp_ms == 1234567890
    assert event.event_type is EventType.DECISION
    assert event.action == "demo:mock"
    assert event.mode == "general"
    assert event.scope == "personal"
    assert event.allowed is True
    assert event.reason == "explicit mock-tool allowlist"


def test_decision_event_is_immutable():
    policy = PolicyEngine()

    decision = policy.evaluate(
        action="test",
        mode=Mode.GENERAL,
        scope=Scope.PERSONAL,
    )

    event = DecisionEvent.from_decision(
        decision,
        event_id="event-002",
        request_id="request-002",
        timestamp_ms=1000,
    )

    try:
        event.allowed = True
    except AttributeError:
        pass
    else:
        raise AssertionError("DecisionEvent must be immutable")


def test_decision_event_json_is_deterministically_serialized():
    policy = PolicyEngine()

    decision = policy.evaluate(
        action="test",
        mode=Mode.SECURITY,
        scope=Scope.AUTHORIZED,
    )

    event = DecisionEvent.from_decision(
        decision,
        event_id="event-003",
        request_id="request-003",
        timestamp_ms=2000,
    )

    expected = (
        '{"action":"test","allowed":false,"event_id":"event-003",'
        '"event_type":"decision","mode":"security",'
        '"reason":"default deny","request_id":"request-003",'
        '"scope":"authorized",'
        '"timestamp_ms":2000}'
    )

    assert event.to_json() == expected
    assert json.loads(event.to_json()) == event.to_dict()
