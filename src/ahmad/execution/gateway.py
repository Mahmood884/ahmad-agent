from ahmad.core.types import Decision
from ahmad.execution.mock_tool import MockTool, ToolResult


class ExecutionGateway:
    """Final execution boundary.

    The gateway never expands authority.
    Denied decisions never reach a tool.
    """

    def __init__(self) -> None:
        self.mock_tool = MockTool()

    def execute(self, decision: Decision) -> ToolResult:
        if not decision.allowed:
            return ToolResult(
                success=False,
                tool="none",
                output="EXECUTION_DENIED",
            )

        if decision.action == "demo:mock":
            return self.mock_tool.run(decision.action)

        return ToolResult(
            success=False,
            tool="none",
            output="EXECUTION_DENIED",
        )
