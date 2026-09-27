from ahmad.core.runtime import AhmadRuntime, AgentRequest
from ahmad.core.types import Mode


def test_runtime_general_request():
    runtime = AhmadRuntime()

    response = runtime.handle(
        AgentRequest("hello Ahmad")
    )

    assert response.mode == Mode.GENERAL
    assert response.allowed is False
    assert response.executed is False


def test_runtime_research_request():
    runtime = AhmadRuntime()

    response = runtime.handle(
        AgentRequest("research GitHub agent tools")
    )

    assert response.mode == Mode.RESEARCH
    assert response.allowed is False
    assert response.executed is False
