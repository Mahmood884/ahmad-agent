from ahmad.core.results import ResultEvent
from ahmad.core.types import Decision
from ahmad.execution.mock_tool import MockTool, ToolResult
from ahmad.execution.registry import ToolMetadata, ToolRegistry
from ahmad.governance.policy import PolicyEngine
from ahmad.memory.store import EventStore


class ExecutionGateway:
    """
    نقطة الإنفاذ الأخيرة. ما فيه عملية تتجاوز هذا الـ gateway.
    كل قرار وكل نتيجة يُسجَّلان بالـ MemoryStore قبل الرجوع للمستدعي.
    """

    def __init__(
        self,
        memory: EventStore,
        policy: PolicyEngine | None = None,
    ):
        self.memory = memory
        self.policy = policy or PolicyEngine()
        self._registry = ToolRegistry()
        self._registry.register(
            "demo:mock",
            ToolMetadata(
                name="mock_tool",
                version="0.1.0",
                capabilities=("demo:mock",),
                input_schema={"type": "string"},
                output_schema={"type": "object"},
                implementation_id="ahmad.mock-tool/v1",
            ),
            MockTool(),
        )

    @property
    def registry(self) -> ToolRegistry:
        """Registry metadata/mutation API; executable bindings remain private."""
        return self._registry

    def binding_id_for_action(self, action: str) -> str | None:
        descriptor = self._registry.get(action)
        return descriptor.binding_id if descriptor is not None else None

    def execute(
        self,
        decision: Decision,
        *,
        decision_event_id: str,
        result_event_id: str,
        request_id: str,
    ) -> ToolResult:
        if not request_id:
            raise ValueError("request_id is required for gateway execution")

        if self.memory.read(result_event_id) is not None:
            raise ValueError("result_event_id already exists; refusing re-execution")

        binding = self._registry._resolve_binding(decision.action)
        verified = self.policy.evaluate(
            decision.action,
            decision.mode,
            decision.scope,
            source=decision.source,
            tool_binding_id=binding.binding_id if binding else None,
        )
        persisted = (
            self.memory.read(decision_event_id)
            if self.memory is not None
            else None
        )
        event_matches = bool(
            persisted
            and persisted.get("event_type") == "decision"
            and persisted.get("event_id") == decision_event_id
            and persisted.get("request_id") == request_id
            and persisted.get("action") == decision.action
            and persisted.get("mode") == decision.mode.value
            and persisted.get("scope") == decision.scope.value
            and persisted.get("allowed") == decision.allowed
            and persisted.get("reason") == decision.reason
            and persisted.get("source") == decision.source
            and persisted.get("tool_binding_id") == decision.tool_binding_id
        )
        result_request_id = persisted.get("request_id", request_id) if persisted else request_id
        if (
            decision.allowed
            and binding is not None
            and self._registry.binding_is_current(binding)
            and decision.tool_binding_id == binding.binding_id
            and verified.allowed
            and verified.reason == decision.reason
            and verified.tool_binding_id == decision.tool_binding_id
            and event_matches
        ):
            try:
                tool_result = binding.tool.run(decision.action)
            except Exception as error:
                tool_result = ToolResult(
                    success=False,
                    tool=binding.metadata.name,
                    output=f"TOOL_EXCEPTION:{type(error).__name__}",
                )
                result_event = ResultEvent.from_tool_result(
                    tool_result,
                    event_id=result_event_id,
                    decision_event_id=decision_event_id,
                    request_id=result_request_id,
                )
                try:
                    self.memory.append(result_event)
                except Exception as storage_error:
                    raise storage_error from error
                raise
        else:
            tool_result = ToolResult(
                success=False,
                tool="none",
                output="EXECUTION_DENIED",
            )

        result_event = ResultEvent.from_tool_result(
            tool_result,
            event_id=result_event_id,
            decision_event_id=decision_event_id,
            request_id=result_request_id,
        )
        self.memory.append(result_event)
        return tool_result
