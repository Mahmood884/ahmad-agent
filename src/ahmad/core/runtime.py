from ahmad.core.types import AgentRequest
from ahmad.governance.policy import PolicyEngine
from ahmad.orchestration.router import Router
from ahmad.execution.gateway import ExecutionGateway
from ahmad.execution.mock_tool import ToolResult


class AhmadRuntime:
    def __init__(self) -> None:
        self.router = Router()
        self.policy = PolicyEngine()
        self.gateway = ExecutionGateway()

    def handle(self, request: AgentRequest) -> ToolResult:
        mode = self.router.route(request.text)

        decision = self.policy.evaluate(
            action=request.text,
            mode=mode,
            scope=request.scope,
        )

        return self.gateway.execute(decision)
