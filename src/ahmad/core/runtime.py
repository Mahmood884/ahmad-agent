from dataclasses import dataclass

from ahmad.core.types import Mode, Scope
from ahmad.orchestration.router import Router
from ahmad.governance.policy import PolicyEngine
from ahmad.execution.gateway import ExecutionGateway


@dataclass(frozen=True)
class AgentRequest:
    text: str
    scope: Scope = Scope.PERSONAL


@dataclass(frozen=True)
class AgentResponse:
    request: str
    mode: Mode
    allowed: bool
    executed: bool
    reason: str


class AhmadRuntime:
    """
    Main Ahmad runtime.

    Intelligence/request
        ↓
    Orchestration
        ↓
    Governance
        ↓
    Execution Gateway
    """

    def __init__(self) -> None:
        self.router = Router()
        self.policy = PolicyEngine()
        self.gateway = ExecutionGateway(self.policy)

    def handle(self, request: AgentRequest) -> AgentResponse:
        mode = self.router.route(request.text)

        result = self.gateway.request(request.text)

        return AgentResponse(
            request=request.text,
            mode=mode,
            allowed=result["allowed"],
            executed=result["executed"],
            reason=result["reason"],
        )
