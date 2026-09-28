import hashlib
import json
import logging
import time
from dataclasses import dataclass

from ahmad.core.config import load_config
from ahmad.core.events import DecisionEvent
from ahmad.core.types import AgentRequest, Mode, Scope
from ahmad.execution.gateway import ExecutionGateway
from ahmad.execution.mock_tool import ToolResult
from ahmad.governance.policy import PolicyEngine
from ahmad.memory.sqlite_store import SQLiteEventStore
from ahmad.memory.store import EventStore
from ahmad.orchestration.router import Router
from ahmad.providers.base import ProviderRequest, ProviderResult, validate_provider_result
from ahmad.providers.registry import ProviderRegistry

logger = logging.getLogger("ahmad.runtime")


@dataclass(frozen=True)
class ProviderOutcome:
    """Provider intelligence plus governance outcomes for its proposed actions."""

    request_id: str
    response: ProviderResult
    tool_results: tuple[ToolResult, ...]


class AhmadRuntime:
    """
    Request → Router (Mode) → PolicyEngine (Decision)
            → ExecutionGateway (DecisionEvent → MemoryStore → MockTool → ResultEvent → MemoryStore)
    """

    def __init__(
        self,
        memory: EventStore | None = None,
        providers: ProviderRegistry | None = None,
        *,
        recover_in_flight_on_startup: bool = False,
    ) -> None:
        config = load_config()
        self.router = Router()
        self.policy = PolicyEngine()
        self.memory = memory or SQLiteEventStore(config.data_dir / "ahmad.db")
        self.gateway = ExecutionGateway(memory=self.memory, policy=self.policy)
        if recover_in_flight_on_startup:
            recovered = self.gateway.recover_orphaned_attempts()
            logger.info("attempt_recovery_complete", extra={"ambiguous_attempts": recovered})
        self.providers = providers or ProviderRegistry()

    def handle(self, request: AgentRequest, *, event_id: str | None = None,
               attempt_id: str | None = None) -> ToolResult:
        return self._handle_request(request, event_id=event_id, source=None, attempt_id=attempt_id)

    def handle_provider_request(
        self,
        provider_name: str,
        prompt: str,
        *,
        scope: Scope = Scope.PERSONAL,
        request_id: str | None = None,
    ) -> ProviderOutcome:
        """Ask a provider for intelligence; route every proposed action back through governance."""
        provider = self.providers.get(provider_name)
        if provider is None:
            raise ValueError(f"unknown provider: {provider_name}")

        provider_request_id = request_id or self._derive_request_id(
            AgentRequest(f"provider:{provider_name}:{prompt}", scope),
            sequence=len(self.memory.read_all()),
        )
        provider_request = ProviderRequest(
            request_id=provider_request_id,
            prompt=prompt,
            mode=self.router.route(prompt),
        )
        response = validate_provider_result(provider.generate(provider_request))
        if not response.success:
            return ProviderOutcome(provider_request_id, response, ())

        results: list[ToolResult] = []
        for index, proposal in enumerate(response.proposed_actions):
            proposal_id = f"{provider_request_id}:proposal:{index}"
            results.append(
                self._handle_request(
                    AgentRequest(proposal.action, scope, request_id=proposal_id),
                    event_id=None,
                    source=f"provider:{provider.name}",
                )
            )
        return ProviderOutcome(provider_request_id, response, tuple(results))

    def _handle_request(
        self,
        request: AgentRequest,
        *,
        event_id: str | None,
        source: str | None,
        attempt_id: str | None = None,
    ) -> ToolResult:
        mode = self.router.route(request.text)
        tool_binding_id = self.gateway.binding_id_for_action(request.text)
        decision = self.policy.evaluate(
            request.text,
            mode,
            request.scope,
            source=source,
            tool_binding_id=tool_binding_id,
        )
        request_id = request.request_id or self._derive_request_id(
            request, sequence=len(self.memory.read_all())
        )
        if event_id is None:
            event_id = (f"decision-{request_id}:retry:{attempt_id}" if attempt_id
                        else f"decision-{request_id}")

        decision_event = DecisionEvent.from_decision(
            decision, event_id=event_id, request_id=request_id
        )
        existing_decision = self.memory.read(event_id)
        if existing_decision is None:
            self.memory.append(decision_event)
        elif existing_decision != decision_event.to_dict():
            raise ValueError("DecisionEvent ID already exists with different authorization context")
        logger.info(
            "governance_decision",
            extra={
                "request_id": request_id,
                "decision_event_id": decision_event.event_id,
                "mode": mode.value,
                "allowed": decision.allowed,
            },
        )
        started = time.monotonic()
        result = self.gateway.execute(
            decision,
            decision_event_id=decision_event.event_id,
            result_event_id=f"{decision_event.event_id}:result",
            request_id=request_id,
            attempt_id=attempt_id,
        )
        logger.info(
            "execution_result",
            extra={
                "request_id": request_id,
                "decision_event_id": decision_event.event_id,
                "tool": result.tool,
                "success": result.success,
                "latency_ms": round((time.monotonic() - started) * 1000),
            },
        )
        return result

    @staticmethod
    def _derive_request_id(request: AgentRequest, *, sequence: int = 0) -> str:
        canonical = json.dumps(
            {
                "text": request.text,
                "scope": request.scope.value,
                "sequence": sequence,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
        return f"req-{digest}"
