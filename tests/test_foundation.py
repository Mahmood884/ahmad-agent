from ahmad.core.identity import IDENTITY
from ahmad.orchestration.router import Router
from ahmad.execution.gateway import ExecutionGateway


def test_identity():
    assert IDENTITY.name == "Ahmad"


def test_router():
    router = Router()
    assert router.route("research GitHub tools").value == "research"


def test_gateway_default_deny():
    gateway = ExecutionGateway()
    result = gateway.request("test action")

    assert result["allowed"] is False
    assert result["executed"] is False
