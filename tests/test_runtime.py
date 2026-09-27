from ahmad.core.runtime import AhmadRuntime
from ahmad.core.types import AgentRequest, Mode, Scope
from ahmad.memory.store import MemoryStore


def test_runtime_general_request_is_denied(tmp_path):
    runtime = AhmadRuntime(
        event_store=MemoryStore(tmp_path / "events.jsonl")
    )

    result = runtime.handle(
        AgentRequest("hello"),
        event_id="event-001",
    )

    assert result.success is False
    assert result.output == "EXECUTION_DENIED"


def test_runtime_research_request_is_denied(tmp_path):
    runtime = AhmadRuntime(
        event_store=MemoryStore(tmp_path / "events.jsonl")
    )

    result = runtime.handle(
        AgentRequest("research this topic"),
        event_id="event-002",
    )

    assert result.success is False
    assert result.output == "EXECUTION_DENIED"


def test_runtime_passes_scope_to_policy(tmp_path):
    runtime = AhmadRuntime(
        event_store=MemoryStore(tmp_path / "events.jsonl")
    )

    captured = {}
    original = runtime.policy.evaluate

    def spy(action, mode, scope):
        captured["action"] = action
        captured["mode"] = mode
        captured["scope"] = scope
        return original(action, mode, scope)

    runtime.policy.evaluate = spy

    runtime.handle(
        AgentRequest(
            "do something",
            scope=Scope.AUTHORIZED,
        ),
        event_id="event-003",
    )

    assert captured["action"] == "do something"
    assert captured["mode"] is Mode.GENERAL
    assert captured["scope"] is Scope.AUTHORIZED


def test_runtime_passes_security_mode_to_policy(tmp_path):
    runtime = AhmadRuntime(
        event_store=MemoryStore(tmp_path / "events.jsonl")
    )

    captured = {}
    original = runtime.policy.evaluate

    def spy(action, mode, scope):
        captured["mode"] = mode
        return original(action, mode, scope)

    runtime.policy.evaluate = spy

    runtime.handle(
        AgentRequest("security audit"),
        event_id="event-004",
    )

    assert captured["mode"] is Mode.SECURITY


def test_mock_action_is_allowed(tmp_path):
    runtime = AhmadRuntime(
        event_store=MemoryStore(tmp_path / "events.jsonl")
    )

    result = runtime.handle(
        AgentRequest("demo:mock"),
        event_id="event-005",
    )

    assert result.success is True
    assert result.tool == "mock_tool"
    assert result.output == "MOCK_EXECUTED:demo:mock"


def test_mock_action_is_denied_in_authorized_scope(tmp_path):
    runtime = AhmadRuntime(
        event_store=MemoryStore(tmp_path / "events.jsonl")
    )

    result = runtime.handle(
        AgentRequest(
            "demo:mock",
            scope=Scope.AUTHORIZED,
        ),
        event_id="event-006",
    )

    assert result.success is False
    assert result.output == "EXECUTION_DENIED"


def test_mock_tool_never_executes_for_unknown_action(tmp_path):
    runtime = AhmadRuntime(
        event_store=MemoryStore(tmp_path / "events.jsonl")
    )

    result = runtime.handle(
        AgentRequest("something:unknown"),
        event_id="event-007",
    )

    assert result.success is False
    assert result.tool == "none"
    assert result.output == "EXECUTION_DENIED"


def test_runtime_persists_decision_before_execution(tmp_path):
    store = MemoryStore(tmp_path / "events.jsonl")
    runtime = AhmadRuntime(event_store=store)

    result = runtime.handle(
        AgentRequest("demo:mock"),
        event_id="event-008",
    )

    assert result.success is True

    events = store.read_all()

    assert len(events) == 1
    assert events[0]["event_id"] == "event-008"
    assert events[0]["event_type"] == "decision"
    assert events[0]["action"] == "demo:mock"
    assert events[0]["allowed"] is True
