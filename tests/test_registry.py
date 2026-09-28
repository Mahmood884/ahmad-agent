import pytest

from ahmad.core.types import Decision, Mode, Scope
from ahmad.core.events import DecisionEvent
from ahmad.execution.gateway import ExecutionGateway
from ahmad.execution.mock_tool import ToolResult
from ahmad.execution.registry import Capability, CapabilityRegistry, ToolMetadata
from ahmad.governance.policy import MOCK_TOOL_BINDING_ID, PolicyEngine
from ahmad.memory.store import MemoryStore


def test_registering_capability_does_not_authorize_it(tmp_path):
    capabilities = CapabilityRegistry()
    capabilities.register(Capability("shell:execute", "Run a shell command", "high"))
    memory = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(memory=memory)
    decision = gateway.policy.evaluate("shell:execute", Mode.GENERAL, Scope.PERSONAL)
    memory.append(DecisionEvent.from_decision(
        decision, event_id="decision-1", request_id="request-1"
    ))
    result = gateway.execute(
        decision, decision_event_id="decision-1", result_event_id="result-1",
        request_id="request-1",
    )

    assert capabilities.get("shell:execute") is not None
    assert not result.success
    assert result.tool == "none"


def test_gateway_rechecks_forged_allowed_decision(tmp_path):
    memory = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(memory=memory)
    decision = Decision(
        action="demo:mock", mode=Mode.SECURITY, scope=Scope.AUTHORIZED,
        allowed=True, reason="explicit mock-tool allowlist",
        tool_binding_id=MOCK_TOOL_BINDING_ID,
    )
    memory.append(DecisionEvent.from_decision(
        decision, event_id="decision-forged", request_id="request-forged"
    ))
    result = gateway.execute(
        decision, decision_event_id="decision-forged", result_event_id="result-forged",
        request_id="request-forged",
    )
    assert not result.success
    assert result.output == "EXECUTION_DENIED"


def test_gateway_requires_persisted_decision_before_tool_execution(tmp_path):
    memory = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(memory=memory)
    decision = Decision(
        action="demo:mock", mode=Mode.GENERAL, scope=Scope.PERSONAL,
        allowed=True, reason="explicit mock-tool allowlist",
        tool_binding_id=MOCK_TOOL_BINDING_ID,
    )
    result = gateway.execute(
        decision, decision_event_id="not-stored", result_event_id="result-unpersisted",
        request_id="request-unpersisted",
    )
    assert result.output == "EXECUTION_DENIED"


def test_registries_reject_duplicate_names():
    capabilities = CapabilityRegistry()
    capabilities.register(Capability("read", "Read data"))
    with pytest.raises(ValueError):
        capabilities.register(Capability("read", "Duplicate"))


def test_tool_metadata_is_descriptive():
    metadata = ToolMetadata("example", "1", capabilities=("example:run",), risk="high")
    assert metadata.capabilities == ("example:run",)
    assert metadata.risk == "high"


def test_replacing_tool_binding_after_authorization_is_denied(tmp_path):
    class ReplacementTool:
        called = False

        def run(self, action):
            self.called = True
            raise AssertionError("replacement implementation executed")

    memory = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(memory=memory)
    original_binding_id = gateway.binding_id_for_action("demo:mock")
    decision = gateway.policy.evaluate(
        "demo:mock", Mode.GENERAL, Scope.PERSONAL,
        tool_binding_id=original_binding_id,
    )
    event = DecisionEvent.from_decision(
        decision, event_id="decision-before-replacement", request_id="request-r1"
    )
    memory.append(event)
    replacement = ReplacementTool()
    gateway.registry.replace_tool("demo:mock", replacement)

    result = gateway.execute(
        decision, decision_event_id=event.event_id,
        result_event_id="result-after-replacement", request_id="request-r1",
    )

    assert gateway.binding_id_for_action("demo:mock") != original_binding_id
    assert result.output == "EXECUTION_DENIED"
    assert replacement.called is False


def test_gateway_denies_in_place_implementation_fingerprint_change(tmp_path):
    class ObservableTool:
        def __init__(self):
            self.calls = 0

        def run(self, action):
            self.calls += 1
            return ToolResult(True, "observable", action)

    memory = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(memory=memory)
    original_tool = ObservableTool()
    gateway.registry.replace_tool("demo:mock", original_tool)
    binding = gateway.registry._resolve_binding("demo:mock")
    original_binding_id = gateway.binding_id_for_action("demo:mock")
    decision = Decision(
        action="demo:mock", mode=Mode.GENERAL, scope=Scope.PERSONAL,
        allowed=True, reason="explicit mock-tool allowlist",
        tool_binding_id=original_binding_id,
    )
    gateway.policy.evaluate = lambda action, mode, scope, *, source=None, tool_binding_id=None: Decision(
        action=action, mode=mode, scope=scope,
        allowed=tool_binding_id == original_binding_id,
        reason="explicit mock-tool allowlist",
        source=source, tool_binding_id=tool_binding_id,
    )
    event = DecisionEvent.from_decision(
        decision, event_id="decision-fingerprint", request_id="request-fingerprint"
    )
    memory.append(event)

    def substituted_implementation(action):
        original_tool.calls += 100
        return ToolResult(True, "substituted", action)

    # Keep the same ToolBinding and binding ID while changing its implementation.
    original_tool.run = substituted_implementation

    result = gateway.execute(
        decision, decision_event_id=event.event_id,
        result_event_id="result-fingerprint", request_id="request-fingerprint",
    )

    assert gateway.binding_id_for_action("demo:mock") == original_binding_id
    assert gateway.registry._resolve_binding("demo:mock") is binding
    assert not gateway.registry.binding_is_current(binding)
    assert result.output == "EXECUTION_DENIED"
    assert original_tool.calls == 0


def test_reusing_request_id_for_different_action_is_denied(tmp_path):
    class ObservableTool:
        def __init__(self):
            self.calls = 0

        def run(self, action):
            self.calls += 1
            return ToolResult(True, "alternate", action)

    memory = MemoryStore(tmp_path / "events.jsonl")
    policy = PolicyEngine()
    gateway = ExecutionGateway(memory=memory, policy=policy)
    original_binding_id = gateway.binding_id_for_action("demo:mock")
    original_decision = policy.evaluate(
        "demo:mock", Mode.GENERAL, Scope.PERSONAL,
        tool_binding_id=original_binding_id,
    )
    event = DecisionEvent.from_decision(
        original_decision, event_id="decision-reused-request", request_id="request-reused"
    )
    memory.append(event)

    alternate_tool = ObservableTool()
    metadata = gateway.registry.get("demo:mock").metadata
    gateway.registry.register("demo:other", metadata, alternate_tool)
    alternate_binding_id = gateway.binding_id_for_action("demo:other")
    policy.evaluate = lambda action, mode, scope, *, source=None, tool_binding_id=None: Decision(
        action=action, mode=mode, scope=scope,
        allowed=action == "demo:other" and tool_binding_id == alternate_binding_id,
        reason="explicit mock-tool allowlist",
        source=source, tool_binding_id=tool_binding_id,
    )
    substituted_decision = Decision(
        action="demo:other", mode=Mode.GENERAL, scope=Scope.PERSONAL,
        allowed=True, reason="explicit mock-tool allowlist",
        tool_binding_id=alternate_binding_id,
    )

    result = gateway.execute(
        substituted_decision, decision_event_id=event.event_id,
        result_event_id="result-reused-request", request_id="request-reused",
    )

    assert result.output == "EXECUTION_DENIED"
    assert alternate_tool.calls == 0
    assert memory.read("result-reused-request")["request_id"] == "request-reused"


def test_gateway_requires_matching_request_id_on_direct_call(tmp_path):
    memory = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(memory=memory)
    binding_id = gateway.binding_id_for_action("demo:mock")
    decision = gateway.policy.evaluate(
        "demo:mock", Mode.GENERAL, Scope.PERSONAL,
        tool_binding_id=binding_id,
    )
    memory.append(DecisionEvent.from_decision(
        decision, event_id="decision-correlation", request_id="request-canonical"
    ))

    result = gateway.execute(
        decision, decision_event_id="decision-correlation",
        result_event_id="result-correlation", request_id="request-other",
    )

    assert result.output == "EXECUTION_DENIED"
    result_event = memory.read("result-correlation")
    assert result_event["request_id"] == "request-canonical"
    assert result_event["success"] is False


def test_tool_exception_persists_failure_result_then_propagates(tmp_path):
    class RaisingTool:
        def run(self, action):
            raise RuntimeError("tool failed")

    memory = MemoryStore(tmp_path / "events.jsonl")
    policy = PolicyEngine()
    gateway = ExecutionGateway(memory=memory, policy=policy)
    gateway.registry.replace_tool("demo:mock", RaisingTool())
    binding_id = gateway.binding_id_for_action("demo:mock")
    decision = Decision(
        action="demo:mock", mode=Mode.GENERAL, scope=Scope.PERSONAL,
        allowed=True, reason="explicit mock-tool allowlist",
        tool_binding_id=binding_id,
    )
    # The fixture explicitly authorizes this test binding so the call reaches the tool.
    policy.evaluate = lambda action, mode, scope, *, source=None, tool_binding_id=None: Decision(
        action=action, mode=mode, scope=scope,
        allowed=tool_binding_id == binding_id,
        reason="explicit mock-tool allowlist",
        source=source, tool_binding_id=tool_binding_id,
    )
    event = DecisionEvent.from_decision(
        decision, event_id="decision-raises", request_id="request-raises"
    )
    memory.append(event)

    with pytest.raises(RuntimeError, match="tool failed"):
        gateway.execute(
            decision, decision_event_id=event.event_id,
            result_event_id="result-raises", request_id="request-raises",
        )

    result = memory.read("result-raises")
    assert result["success"] is False
    assert result["output"] == "TOOL_EXCEPTION:RuntimeError"
    assert result["request_id"] == "request-raises"
    assert result["decision_event_id"] == event.event_id


def test_successful_execution_persists_success_result(tmp_path):
    memory = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(memory=memory)
    binding_id = gateway.binding_id_for_action("demo:mock")
    decision = gateway.policy.evaluate(
        "demo:mock", Mode.GENERAL, Scope.PERSONAL,
        tool_binding_id=binding_id,
    )
    event = DecisionEvent.from_decision(
        decision, event_id="decision-success", request_id="request-success"
    )
    memory.append(event)

    result = gateway.execute(
        decision, decision_event_id=event.event_id,
        result_event_id="result-success", request_id="request-success",
    )

    assert result.success is True
    assert memory.read("result-success")["success"] is True


def test_result_store_failure_is_raised_after_execution(tmp_path):
    class SideEffectTool:
        def __init__(self, external_state):
            self.external_state = external_state

        def run(self, action):
            self.external_state["executions"] += 1
            return ToolResult(True, "side-effect", "external change made")

    class FailingResultStore(MemoryStore):
        def append(self, event):
            if getattr(event, "event_type", None) == "result":
                raise OSError("result storage unavailable")
            super().append(event)

    memory = FailingResultStore(tmp_path / "events.jsonl")
    policy = PolicyEngine()
    gateway = ExecutionGateway(memory=memory, policy=policy)
    external_state = {"executions": 0}
    gateway.registry.replace_tool("demo:mock", SideEffectTool(external_state))
    binding_id = gateway.binding_id_for_action("demo:mock")
    decision = Decision(
        action="demo:mock", mode=Mode.GENERAL, scope=Scope.PERSONAL,
        allowed=True, reason="explicit mock-tool allowlist",
        tool_binding_id=binding_id,
    )
    policy.evaluate = lambda action, mode, scope, *, source=None, tool_binding_id=None: Decision(
        action=action, mode=mode, scope=scope,
        allowed=tool_binding_id == binding_id,
        reason="explicit mock-tool allowlist",
        source=source, tool_binding_id=tool_binding_id,
    )
    event = DecisionEvent.from_decision(
        decision, event_id="decision-store-fails", request_id="request-store-fails"
    )
    memory.append(event)

    with pytest.raises(OSError, match="result storage unavailable"):
        gateway.execute(
            decision, decision_event_id=event.event_id,
            result_event_id="result-store-fails", request_id="request-store-fails",
        )

    assert external_state["executions"] == 1
    events = memory.read_all()
    assert [item["event_type"] for item in events] == [
        "decision", "attempt_created", "attempt_started", "attempt_ambiguous"
    ]
    assert events[-1]["state"] == "ambiguous"
    assert events[-1]["reason"].startswith("result persistence failed")
