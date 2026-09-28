from dataclasses import dataclass

from ahmad.core.types import EffectStatus


@dataclass(frozen=True)
class ToolResult:
    success: bool
    tool: str
    output: str
    effect_status: EffectStatus | None = None


class MockTool:
    """Safe in-process tool used only for execution-path testing."""

    name = "mock_tool"

    def run(self, action: str) -> ToolResult:
        return ToolResult(
            success=True,
            tool=self.name,
            output=f"MOCK_EXECUTED:{action}",
            effect_status=EffectStatus.APPLIED,
        )
