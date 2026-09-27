from ahmad.core.runtime import AhmadRuntime
from ahmad.core.types import Scope
from ahmad.execution.mock_tool import ToolResult
from ahmad.memory.store import MemoryStore
from ahmad.providers.base import ProviderAdapter, ProviderResult, ProposedAction
from ahmad.providers.registry import ProviderRegistry


class TrackingTool:
    def __init__(self, store):
        self.store = store
        self.calls = 0

    def run(self, action: str) -> ToolResult:
        self.calls += 1
        events = self.store.read_all()
        decision = events[-1]
        assert decision["event_type"] == "decision"
        assert decision["allowed"] is True
        assert decision["source"] == "provider:mock-provider"
        return ToolResult(True, "tracking-tool", f"executed:{action}")


def test_provider_can_propose_action_but_cannot_execute_it(tmp_path):
    calls_during_transport = []
    store = MemoryStore(tmp_path / "events.jsonl")
    providers = ProviderRegistry()
    runtime = AhmadRuntime(memory=store, providers=providers)
    tool = TrackingTool(store)
    policy_calls = []
    evaluate = runtime.policy.evaluate

    def recording_evaluate(action, mode, scope, *, source=None, tool_binding_id=None):
        policy_calls.append((action, source))
        return evaluate(
            action, mode, scope, source=source, tool_binding_id=tool_binding_id
        )

    runtime.policy.evaluate = recording_evaluate

    def transport(request):
        calls_during_transport.append(tool.calls)
        return ProviderResult(
            provider="forged-name-is-overridden",
            success=True,
            output="I recommend a mock action.",
            plan="Use the governed demo tool.",
            proposed_actions=(ProposedAction("demo:mock"),),
            metadata={"model": "test-model"},
        )

    providers.register(ProviderAdapter(transport, name="mock-provider"))

    outcome = runtime.handle_provider_request(
        "mock-provider", "suggest a safe action", request_id="provider-request-1"
    )

    assert calls_during_transport == [0]
    assert outcome.response.text == "I recommend a mock action."
    assert outcome.response.plan == "Use the governed demo tool."
    assert outcome.response.metadata == {"model": "test-model"}
    assert len(outcome.response.proposed_actions) == 1
    assert len(outcome.tool_results) == 1
    assert outcome.tool_results[0].success is True
    assert outcome.tool_results[0].tool == "mock_tool"
    assert policy_calls == [
        ("demo:mock", "provider:mock-provider"),
        ("demo:mock", "provider:mock-provider"),
    ]


def test_denied_provider_proposal_is_recorded_and_never_reaches_tool(tmp_path):
    store = MemoryStore(tmp_path / "events.jsonl")
    providers = ProviderRegistry()
    providers.register(
        ProviderAdapter(
            lambda request: ProviderResult(
                provider="mock-provider",
                success=True,
                proposed_actions=(ProposedAction("shell:execute"),),
            ),
            name="mock-provider",
        )
    )
    runtime = AhmadRuntime(memory=store, providers=providers)
    tool = TrackingTool(store)

    outcome = runtime.handle_provider_request(
        "mock-provider", "run shell", request_id="provider-request-2"
    )

    assert len(outcome.tool_results) == 1
    assert outcome.tool_results[0].success is False
    assert tool.calls == 0
    decision, result = store.read_all()
    assert decision["action"] == "shell:execute"
    assert decision["source"] == "provider:mock-provider"
    assert decision["allowed"] is False
    assert result["decision_event_id"] == decision["event_id"]
    assert result["success"] is False


def test_provider_selection_does_not_change_policy(tmp_path):
    store = MemoryStore(tmp_path / "events.jsonl")
    providers = ProviderRegistry()
    providers.register(ProviderAdapter(
        lambda request: ProviderResult(
            provider="provider", success=True,
            proposed_actions=(ProposedAction("unknown:action"),),
        ), name="mock-provider"
    ))
    runtime = AhmadRuntime(memory=store, providers=providers)
    tool = TrackingTool(store)

    outcome = runtime.handle_provider_request(
        "mock-provider", "unknown request", scope=Scope.PERSONAL,
        request_id="provider-request-3",
    )

    assert outcome.tool_results[0].output == "EXECUTION_DENIED"
    assert tool.calls == 0
