import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping

from ahmad.core.config import load_config
from ahmad.core.conversation import ConversationContext, sanitize_conversation_id
from ahmad.core.events import DecisionEvent
from ahmad.core.types import AgentRequest, Mode, Scope
from ahmad.execution.gateway import ExecutionGateway
from ahmad.execution.mock_tool import ToolResult
from ahmad.governance.policy import PolicyEngine
from ahmad.memory.sqlite_store import SQLiteEventStore
from ahmad.memory.store import EventStore
from ahmad.orchestration.router import Router
from ahmad.providers.base import ProviderRequest, ProviderResult, validate_provider_result
from ahmad.providers.costs import ProviderCostLedger
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
        cost_ledger_path: Path | None = None,
        provider_rates: Mapping[str, Mapping[str, float]] | None = None,
        conversations_dir: Path | None = None,
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
        self._conversations_dir = conversations_dir or config.data_dir / "conversations"
        self._conversations: dict[str, ConversationContext] = {}
        self.cost_ledger = ProviderCostLedger(
            cost_ledger_path or config.data_dir / "provider_costs.jsonl",
            provider_rates,
        )
        self.last_stream_outcome: ProviderOutcome | None = None

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
        conversation_id: str = "default",
    ) -> ProviderOutcome:
        """Ask a provider for intelligence; route every proposed action back through governance.

        `conversation_id` selects a bounded, persisted turn history that is
        prepended to `prompt` before it reaches the provider transport. A
        conversation with no prior turns renders unchanged — single-shot
        callers see identical behavior to before this existed.
        """
        provider = self.providers.get(provider_name)
        if provider is None:
            raise ValueError(f"unknown provider: {provider_name}")

        conversation = self._get_conversation(conversation_id)

        provider_request_id = request_id or self._derive_request_id(
            AgentRequest(f"provider:{provider_name}:{prompt}", scope),
            sequence=len(self.memory.read_all()),
        )
        rendered_prompt = conversation.render_prompt(prompt)
        provider_request = ProviderRequest(
            request_id=provider_request_id,
            prompt=rendered_prompt,
            mode=self.router.route(prompt),
        )
        try:
            response = validate_provider_result(provider.generate(provider_request))
        except Exception:
            self.cost_ledger.record(provider.name, provider_request_id, rendered_prompt, None)
            raise
        self.cost_ledger.record(provider.name, provider_request_id, rendered_prompt, response)
        conversation.add_turn("user", prompt)
        return self._complete_provider_response(
            provider, response, provider_request_id, conversation, scope
        )

    def stream_provider_request(
        self,
        provider_name: str,
        prompt: str,
        *,
        scope: Scope = Scope.PERSONAL,
        request_id: str | None = None,
        conversation_id: str = "default",
    ) -> Iterator[str]:
        """Yield response text as produced, then govern any final proposed actions.

        After iteration completes, ``last_stream_outcome`` contains the same
        ProviderOutcome shape returned by ``handle_provider_request``.
        """
        self.last_stream_outcome = None
        provider = self.providers.get(provider_name)
        if provider is None:
            raise ValueError(f"unknown provider: {provider_name}")

        conversation = self._get_conversation(conversation_id)
        provider_request_id = request_id or self._derive_request_id(
            AgentRequest(f"provider:{provider_name}:{prompt}", scope),
            sequence=len(self.memory.read_all()),
        )
        rendered_prompt = conversation.render_prompt(prompt)
        provider_request = ProviderRequest(
            request_id=provider_request_id,
            prompt=rendered_prompt,
            mode=self.router.route(prompt),
        )
        conversation.add_turn("user", prompt)
        chunks: list[str] = []
        try:
            generate_stream = getattr(provider, "generate_stream", None)
            if callable(generate_stream):
                stream = iter(generate_stream(provider_request))
                response = None
                while True:
                    try:
                        chunk = next(stream)
                    except StopIteration as stop:
                        response = stop.value
                        break
                    if not isinstance(chunk, str):
                        raise ValueError("provider stream yielded a non-text chunk")
                    chunks.append(chunk)
                    yield chunk
                if response is None:
                    response = ProviderResult(provider.name, True, "".join(chunks))
            else:
                response = validate_provider_result(provider.generate(provider_request))
                if response.text:
                    chunks.append(response.text)
                    yield response.text
            response = validate_provider_result(response)
        except Exception:
            self.cost_ledger.record(provider.name, provider_request_id, rendered_prompt, None)
            raise

        self.cost_ledger.record(provider.name, provider_request_id, rendered_prompt, response)
        self.last_stream_outcome = self._complete_provider_response(
            provider, response, provider_request_id, conversation, scope
        )

    def reset_conversation(self, conversation_id: str = "default") -> None:
        """Clear in-memory history for a conversation (persisted file is left as-is)."""
        self._get_conversation(conversation_id).clear()

    def _complete_provider_response(
        self,
        provider,
        response: ProviderResult,
        request_id: str,
        conversation: ConversationContext,
        scope: Scope,
    ) -> ProviderOutcome:
        if response.success:
            conversation.add_turn("assistant", response.text)
        if not response.success:
            return ProviderOutcome(request_id, response, ())

        results: list[ToolResult] = []
        for index, proposal in enumerate(response.proposed_actions):
            proposal_id = f"{request_id}:proposal:{index}"
            results.append(
                self._handle_request(
                    AgentRequest(proposal.action, scope, request_id=proposal_id),
                    event_id=None,
                    source=f"provider:{provider.name}",
                )
            )
        return ProviderOutcome(request_id, response, tuple(results))

    def _get_conversation(self, conversation_id: str) -> ConversationContext:
        conversation_id = sanitize_conversation_id(conversation_id)
        if conversation_id not in self._conversations:
            self._conversations[conversation_id] = ConversationContext(
                conversation_id,
                path=self._conversations_dir / f"{conversation_id}.jsonl",
            )
        return self._conversations[conversation_id]

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
        descriptor = self.gateway.registry.get(request.text)
        redact_input = bool(
            descriptor
            and descriptor.metadata.implementation_config.get("redact_input")
        )
        decision_action = descriptor.action if redact_input else request.text
        network_approved = False
        if decision_action == "component_lib" and request.text.startswith("component_lib:"):
            try:
                component_arguments = json.loads(request.text[len("component_lib:"):])
                network_approved = (
                    isinstance(component_arguments, dict)
                    and component_arguments.get("allow_network") is True
                )
            except json.JSONDecodeError:
                pass
        if network_approved:
            decision = self.policy.evaluate(
                decision_action,
                mode,
                request.scope,
                source=source,
                tool_binding_id=tool_binding_id,
                network_approved=True,
            )
        else:
            decision = self.policy.evaluate(
                decision_action,
                mode,
                request.scope,
                source=source,
                tool_binding_id=tool_binding_id,
            )
        request_for_id = (
            AgentRequest(decision_action, request.scope)
            if redact_input and request.request_id is None
            else request
        )
        request_id = request.request_id or self._derive_request_id(
            request_for_id, sequence=len(self.memory.read_all())
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
            execution_action=request.text if redact_input else None,
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
