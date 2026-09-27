from ahmad.core.identity import IDENTITY
from ahmad.core.types import AgentRequest, Mode, Scope
from ahmad.governance.policy import PolicyEngine
from ahmad.orchestration.router import Router
from ahmad.execution.gateway import ExecutionGateway


def test_identity():
    assert IDENTITY.name == "Ahmad"
    assert IDENTITY.role == "Executive Agent"


def test_router():
    router = Router()

    assert router.route("hello") is Mode.GENERAL
    assert router.route("research this") is Mode.RESEARCH
    assert router.route("security audit") is Mode.SECURITY


def test_gateway_default_deny():
    policy = PolicyEngine()
    gateway = ExecutionGateway()

    decision = policy.evaluate(
        action="test action",
        mode=Mode.GENERAL,
        scope=Scope.PERSONAL,
    )

    assert decision.allowed is False
    result = gateway.execute(decision)
    assert result.success is False
    assert result.tool == "none"
    assert result.output == "EXECUTION_DENIED"
