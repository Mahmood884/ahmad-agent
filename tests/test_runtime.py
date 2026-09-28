from pathlib import Path

from ahmad.core.runtime import AhmadRuntime
from ahmad.core.types import AgentRequest
from ahmad.execution.mock_tool import ToolResult
from ahmad.core.types import Decision, Mode, Scope
from ahmad.memory.store import MemoryStore


def test_runtime_general_request(tmp_path: Path):
    runtime = AhmadRuntime(memory=MemoryStore(tmp_path / "events.jsonl"))
    result = runtime.handle(AgentRequest("hello Ahmad"))

    assert result.success is False
    assert result.tool == "none"
    assert result.output == "EXECUTION_DENIED"
    events = runtime.memory.read_all()
    assert [event["event_type"] for event in events] == ["decision", "result"]
    assert events[1]["decision_event_id"] == events[0]["event_id"]


def test_runtime_research_request(tmp_path: Path):
    runtime = AhmadRuntime(memory=MemoryStore(tmp_path / "events.jsonl"))
    result = runtime.handle(AgentRequest("research GitHub agent tools"))

    assert result.success is False
    assert result.output == "EXECUTION_DENIED"


def test_runtime_persists_decision_before_tool_and_result_after(tmp_path: Path):
    memory = MemoryStore(tmp_path / "events.jsonl")
    runtime = AhmadRuntime(memory=memory)

    class ObservingTool:
        def run(self, action: str) -> ToolResult:
            events = memory.read_all()
            assert [event["event_type"] for event in events] == [
                "decision", "attempt_created", "attempt_started"
            ]
            return ToolResult(True, "observing_tool", f"observed:{action}")

    runtime.gateway.registry.replace_tool("demo:mock", ObservingTool())
    approved_binding_id = runtime.gateway.binding_id_for_action("demo:mock")
    original_evaluate = runtime.policy.evaluate

    def test_policy(action, mode, scope, *, source=None, tool_binding_id=None):
        if (
            action == "demo:mock"
            and mode is Mode.GENERAL
            and scope is Scope.PERSONAL
            and tool_binding_id == approved_binding_id
        ):
            return Decision(
                action, mode, scope, True, "test-only exact binding approval",
                source=source, tool_binding_id=tool_binding_id,
            )
        return original_evaluate(
            action, mode, scope, source=source, tool_binding_id=tool_binding_id
        )

    runtime.policy.evaluate = test_policy

    result = runtime.handle(AgentRequest("demo:mock"), event_id="decision-allowed")

    assert result.success is True
    assert result.output == "observed:demo:mock"
    events = memory.read_all()
    assert [event["event_type"] for event in events] == [
        "decision", "attempt_created", "attempt_started", "result"
    ]
    assert events[0]["allowed"] is True
    assert events[1]["decision_event_id"] == events[0]["event_id"]
    assert events[3]["output"] == result.output


def test_denied_runtime_request_never_calls_tool(tmp_path: Path):
    class TrackingTool:
        called = False

        def run(self, action: str):
            self.called = True
            raise AssertionError("denied request reached tool")

    runtime = AhmadRuntime(memory=MemoryStore(tmp_path / "events.jsonl"))
    tool = TrackingTool()
    runtime.gateway.registry.replace_tool("demo:mock", tool)
    binding_id = runtime.gateway.binding_id_for_action("demo:mock")

    def test_policy(action, mode, scope, *, source=None, tool_binding_id=None):
        allowed = action == "demo:mock" and scope is Scope.PERSONAL and tool_binding_id == binding_id
        return Decision(
            action, mode, scope, allowed,
            "test-only exact binding approval" if allowed else "default deny",
            source=source, tool_binding_id=tool_binding_id,
        )

    runtime.policy.evaluate = test_policy

    result = runtime.handle(AgentRequest("demo:mock", scope=Scope.AUTHORIZED))

    assert result.output == "EXECUTION_DENIED"
    assert tool.called is False
    events = runtime.memory.read_all()
    assert len(events) == 2
    assert events[1]["event_type"] == "result"
    assert events[1]["success"] is False


def test_repeated_identical_requests_receive_distinct_stable_ids(tmp_path: Path):
    memory = MemoryStore(tmp_path / "events.jsonl")
    first_runtime = AhmadRuntime(memory=memory)
    first_runtime.handle(AgentRequest("hello Ahmad"))
    first_id = memory.read_all()[0]["request_id"]

    second_runtime = AhmadRuntime(memory=memory)
    second_runtime.handle(AgentRequest("hello Ahmad"))
    second_id = memory.read_all()[2]["request_id"]

    assert first_id != second_id
