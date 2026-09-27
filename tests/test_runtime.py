from ahmad.core.runtime import AhmadRuntime
from ahmad.core.types import AgentRequest, Mode, Scope


def test_runtime_general_request_is_denied():
    runtime = AhmadRuntime()

    result = runtime.handle(
        AgentRequest("hello")
    )

    assert result.success is False
    assert result.output == "EXECUTION_DENIED"


def test_runtime_research_request_is_denied():
    runtime = AhmadRuntime()

    result = runtime.handle(
        AgentRequest("research this topic")
    )

    assert result.success is False
    assert result.output == "EXECUTION_DENIED"


def test_runtime_passes_scope_to_policy():
    runtime = AhmadRuntime()

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
        )
    )

    assert captured["action"] == "do something"
    assert captured["mode"] is Mode.GENERAL
    assert captured["scope"] is Scope.AUTHORIZED


def test_runtime_passes_security_mode_to_policy():
    runtime = AhmadRuntime()

    captured = {}

    original = runtime.policy.evaluate

    def spy(action, mode, scope):
        captured["mode"] = mode
        return original(action, mode, scope)

    runtime.policy.evaluate = spy

    runtime.handle(
        AgentRequest("security audit")
    )

    assert captured["mode"] is Mode.SECURITY


def test_mock_action_is_allowed():
    runtime = AhmadRuntime()

    result = runtime.handle(
        AgentRequest("demo:mock")
    )

    assert result.success is True
    assert result.tool == "mock_tool"
    assert result.output == "MOCK_EXECUTED:demo:mock"


def test_mock_action_is_denied_in_authorized_scope():
    runtime = AhmadRuntime()

    result = runtime.handle(
        AgentRequest(
            "demo:mock",
            scope=Scope.AUTHORIZED,
        )
    )

    assert result.success is False
    assert result.output == "EXECUTION_DENIED"


def test_mock_tool_never_executes_for_unknown_action():
    runtime = AhmadRuntime()

    result = runtime.handle(
        AgentRequest("something:unknown")
    )

    assert result.success is False
    assert result.tool == "none"
    assert result.output == "EXECUTION_DENIED"
