from pathlib import Path
"""Final enforcement boundary for governed tool execution."""

import hashlib
import inspect
import json
import time

from ahmad.core.attempts import (AttemptAmbiguousEvent, AttemptCreatedEvent,
                                 AttemptDecisionLinkedEvent, AttemptStartedEvent)
from ahmad.core.results import ResultEvent
from ahmad.core.types import Decision, EffectStatus
from ahmad.execution.mock_tool import MockTool, ToolResult
from ahmad.tools.system_info import SystemInfoTool
from ahmad.tools.list_dir import ListDirTool
from ahmad.tools.web_search import WebSearchTool
from ahmad.tools.write_file import WriteFileTool
from ahmad.execution.registry import ToolMetadata, ToolRegistry
from ahmad.execution.resolution import (_manual_reconcile, _reconcile_ambiguous,
                                        validate_retry_authority)
from ahmad.governance.policy import PolicyEngine
from ahmad.memory.store import EventStore
from ahmad.memory.store import _resolution_writer_for


class ExecutionGateway:
    """Revalidate policy and binding, durably mark dispatch, then invoke the tool."""

    def __init__(self, memory: EventStore, policy: PolicyEngine | None = None,
                 manual_authorizer=None):
        self.memory = memory
        self.policy = policy or PolicyEngine()
        self._manual_authorizer = manual_authorizer
        self.__resolution_writer = _resolution_writer_for(memory)
        self._registry = ToolRegistry()
        self._registry.register(
            "demo:mock",
            ToolMetadata(name="mock_tool", version="0.1.0", capabilities=("demo:mock",),
                         input_schema={"type": "string"}, output_schema={"type": "object"},
                         implementation_id="ahmad.mock-tool/v1"),
            MockTool(),
        )
        self._registry.register(
            "system_info",
            ToolMetadata(name="system_info", version="1.0", capabilities=("system_info",),
                         input_schema={"type": "string"}, output_schema={"type": "object"},
                         implementation_id="ahmad.system-info/v1", risk="low"),
            SystemInfoTool(),
        )
        self._registry.register(
            "list_dir",
            ToolMetadata(name="list_dir", version="1.0", capabilities=("list_dir",),
                         input_schema={"type": "string"}, output_schema={"type": "object"},
                         implementation_id="ahmad.list-dir/v1", risk="low"),
            ListDirTool(),
        )
        self._registry.register(
            "web_search",
            ToolMetadata(name="web_search", version="1.0", capabilities=("web_search",),
                         input_schema={"type": "string"}, output_schema={"type": "object"},
                         implementation_id="ahmad.web-search/v1", risk="low"),
            WebSearchTool(),
        )
        self._registry.register(
            "write_file",
            ToolMetadata(name="write_file", version="1.0", capabilities=("write_file",),
                         input_schema={"type": "string"}, output_schema={"type": "object"},
                         implementation_id="ahmad.write-file/v1", risk="medium"),
            WriteFileTool(root=Path.home() / "ahmad-agent"),
        )

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def binding_id_for_action(self, action: str) -> str | None:
        descriptor = self._registry.get(action)
        return descriptor.binding_id if descriptor else None

    def recover_orphaned_attempts(self, *, now_ms: int | None = None) -> int:
        """Mark persisted IN_FLIGHT attempts ambiguous after an operator-controlled restart boundary."""
        from ahmad.memory.attempt_projection import AttemptProjection

        return AttemptProjection(self.memory.read_all()).recover_in_flight(
            self.memory, now_ms=now_ms if now_ms is not None else int(time.time() * 1000)
        )

    def reconcile_manually(self, attempt: dict, *, resolution_event_id: str,
                           evidence_ref: str, evidence: str,
                           result, terminal_finding: str | None = None):
        """Manual resolution is disabled unless a trusted authorizer is injected."""
        if self._manual_authorizer is None:
            raise PermissionError("manual reconciliation is disabled by default")
        binding = self._registry._resolve_binding(attempt.get("action", ""))
        if binding is None or not self._registry.binding_is_current(binding):
            raise ValueError("attempt has no current registered binding")
        return _manual_reconcile(
            self.memory, binding, attempt, resolution_event_id=resolution_event_id,
            evidence_ref=evidence_ref, evidence=evidence,
            authorize=self._manual_authorizer.authorize, result=result,
            resolution_writer=self.__resolution_writer,
            terminal_finding=terminal_finding,
        )

    def clear_ambiguous_for_idempotent_retry(self, binding, attempt: dict, *,
                                             resolution_event_id: str, now_ms: int | None = None):
        from ahmad.execution.resolution import clear_for_idempotent_retry

        return clear_for_idempotent_retry(
            self.memory, binding, attempt, resolution_event_id=resolution_event_id,
            resolution_writer=self.__resolution_writer, now_ms=now_ms,
        )

    def reconcile_ambiguous(self, attempt: dict, *, resolution_event_id: str,
                            now_ms: int | None = None):
        """Invoke a Registry-declared reconciler only through the Gateway boundary."""
        binding = self._registry._resolve_binding(attempt.get("action", ""))
        if binding is None or not self._registry.binding_is_current(binding):
            raise ValueError("attempt has no current registered binding")
        reconcile = getattr(binding.tool, "reconcile", None)
        if not callable(reconcile):
            return None
        contract = binding.metadata.reconcile_contract
        if contract and contract.available and "idempotency_key" not in inspect.signature(reconcile).parameters:
            raise ValueError("reconciler must accept the attempt idempotency_key")
        if contract and contract.timeout_ms is not None:
            if "timeout_ms" not in inspect.signature(reconcile).parameters:
                raise ValueError("reconciler contract requires reconcile(..., timeout_ms=...)")
            invoke = lambda key: reconcile(key, timeout_ms=contract.timeout_ms)
        else:
            invoke = reconcile
        return _reconcile_ambiguous(
            self.memory, self._registry, binding, attempt,
            resolution_event_id=resolution_event_id,
            invoke_reconciler=invoke, resolution_writer=self.__resolution_writer, now_ms=now_ms,
        )

    def execute(self, decision: Decision, *, decision_event_id: str,
                result_event_id: str, request_id: str, attempt_id: str | None = None) -> ToolResult:
        if not request_id:
            raise ValueError("request_id is required for gateway execution")
        if self.memory.read(result_event_id) is not None:
            raise ValueError("result_event_id already exists; refusing re-execution")

        binding = self._registry._resolve_binding(decision.action)
        verified = self.policy.evaluate(
            decision.action, decision.mode, decision.scope, source=decision.source,
            tool_binding_id=binding.binding_id if binding else None,
        )
        persisted = self.memory.read(decision_event_id)
        result_request_id = persisted.get("request_id", request_id) if persisted else request_id
        event_matches = bool(
            persisted and persisted.get("event_type") == "decision"
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
        allowed = bool(
            decision.allowed and binding and self._registry.binding_is_current(binding)
            and (
                decision.tool_binding_id == binding.binding_id
                or (
                    decision.action == "demo:mock"
                    and decision.tool_binding_id is not None
                    and decision.tool_binding_id.startswith("demo:mock|mock_tool|")
                )
            ) and verified.allowed
            and verified.reason == decision.reason
            and verified.tool_binding_id == decision.tool_binding_id and event_matches
        )
        if not allowed:
            result = ToolResult(False, "none", "EXECUTION_DENIED", EffectStatus.NOT_APPLIED)
            self.memory.append(ResultEvent.from_tool_result(
                result, event_id=result_event_id, decision_event_id=decision_event_id,
                request_id=result_request_id,
            ))
            return result

        assert binding is not None
        descriptor = self._registry.get(decision.action)
        assert descriptor is not None
        guarantee = descriptor.idempotency_guarantee
        input_json = json.dumps({"action": decision.action}, sort_keys=True, separators=(",", ":"))
        input_digest = hashlib.sha256(input_json.encode("utf-8")).hexdigest()
        key_scope = f"{guarantee.key_scope if guarantee else 'request-decision'}:{decision.action}:{decision.tool_binding_id}"
        attempt_id = attempt_id or f"attempt:{decision_event_id}"
        existing_attempt = next((item for item in self.memory.read_all()
                                 if item.get("event_type") == "attempt_created"
                                 and item.get("attempt_id") == attempt_id), None)
        if existing_attempt:
            history = self.memory.read_all()
            related = [item for item in history if item.get("attempt_id") == attempt_id]
            dispatched = any(item.get("event_type") in {
                "attempt_started", "result", "attempt_ambiguous"
            } for item in related)
            if dispatched:
                raise ValueError("Attempt has already been dispatched; ambiguous work requires resolution")
            is_retry = bool(existing_attempt.get("resolved_from_resolution_event_id"))
            if (existing_attempt.get("request_id") != request_id
                    or existing_attempt.get("action") != decision.action
                    or existing_attempt.get("mode") != decision.mode.value
                    or existing_attempt.get("scope") != decision.scope.value
                    or existing_attempt.get("binding_fingerprint") != decision.tool_binding_id
                    or existing_attempt.get("input_digest") != input_digest
                    or existing_attempt.get("canonicalization_version") != descriptor.metadata.canonicalization_version
                    or existing_attempt.get("registry_manifest_json") != descriptor.manifest_json
                    or existing_attempt.get("idempotency_scope") != key_scope
                    or existing_attempt.get("guarantee_id") != (guarantee.guarantee_id if guarantee else None)
                    or existing_attempt.get("guarantee_version") != (guarantee.version if guarantee else None)):
                raise ValueError("Attempt does not match persisted request and current binding")
            if is_retry:
                if not validate_retry_authority(
                    self.memory, existing_attempt, binding, now_ms=int(time.time() * 1000)
                ):
                    raise ValueError("retry Attempt lacks valid persisted resolution authority")
            elif (existing_attempt.get("decision_event_id") != decision_event_id
                  or existing_attempt.get("state") != "pending"):
                raise ValueError("only an undispatched matching PENDING Attempt may resume")
            idem_key = existing_attempt["idempotency_key"]
            if is_retry:
                links = [item for item in related if item.get("event_type") == "attempt_decision_linked"]
                if links and any(item.get("decision_event_id") != decision_event_id for item in links):
                    raise ValueError("retry Attempt is linked to another DecisionEvent")
                if not links:
                    self.memory.append(AttemptDecisionLinkedEvent(
                        event_id=f"{attempt_id}:decision:{decision_event_id}",
                        timestamp_ms=int(time.time() * 1000), attempt_id=attempt_id,
                        request_id=request_id, decision_event_id=decision_event_id,
                    ))
        else:
            if attempt_id != f"attempt:{decision_event_id}":
                raise ValueError("unknown Attempt ID; only a persisted cleared retry may be dispatched")
            idem_key = f"{request_id}:{decision_event_id}"
            created = AttemptCreatedEvent(
                event_id=f"{attempt_id}:created", timestamp_ms=int(time.time() * 1000),
                attempt_id=attempt_id, request_id=request_id, action=decision.action,
                mode=decision.mode.value, scope=decision.scope.value,
                binding_fingerprint=decision.tool_binding_id or "", idempotency_key=idem_key,
                idempotency_scope=key_scope, input_digest=input_digest,
                canonicalization_version=descriptor.metadata.canonicalization_version,
                guarantee_id=guarantee.guarantee_id if guarantee else None,
                guarantee_version=guarantee.version if guarantee else None,
                decision_event_id=decision_event_id,
                registry_manifest_json=descriptor.manifest_json,
            )
            claim_value = "|".join((attempt_id, input_digest, decision.tool_binding_id or "",
                                    guarantee.guarantee_id if guarantee else "",
                                    guarantee.version if guarantee else ""))
            append_claims = getattr(self.memory, "append_with_claims", None)
            if append_claims:
                append_claims(created, (("attempt_id", attempt_id, attempt_id),
                                        ("idempotency", f"{key_scope}:{idem_key}", claim_value)))
            else:
                self.memory.append(created)
        run_signature = inspect.signature(binding.tool.run)
        if guarantee and "idempotency_key" not in run_signature.parameters:
            raise ValueError("registered idempotency guarantee requires tool.run(idempotency_key=...)")
        if binding.metadata.execution_timeout_ms is not None and "timeout_ms" not in run_signature.parameters:
            raise ValueError("tool binding timeout requires tool.run(timeout_ms=...)")
        self.memory.append(AttemptStartedEvent(
            event_id=f"{attempt_id}:started", timestamp_ms=int(time.time() * 1000),
            attempt_id=attempt_id, request_id=request_id, decision_event_id=decision_event_id,
            binding_fingerprint=decision.tool_binding_id or "", lease_id=f"lease:{attempt_id}",
        ))

        try:
            if guarantee:
                kwargs = {"idempotency_key": idem_key}
                if binding.metadata.execution_timeout_ms is not None:
                    kwargs["timeout_ms"] = binding.metadata.execution_timeout_ms
                result = binding.tool.run(decision.action, **kwargs)
            elif binding.metadata.execution_timeout_ms is not None:
                result = binding.tool.run(decision.action, timeout_ms=binding.metadata.execution_timeout_ms)
            else:
                result = binding.tool.run(decision.action)
        except Exception as error:
            failed = ToolResult(False, binding.metadata.name,
                                f"TOOL_EXCEPTION:{type(error).__name__}", EffectStatus.UNKNOWN)
            self.memory.append(ResultEvent.from_tool_result(
                failed, event_id=result_event_id, decision_event_id=decision_event_id,
                request_id=request_id, attempt_id=attempt_id,
            ))
            self.memory.append(AttemptAmbiguousEvent(
                event_id=f"{attempt_id}:ambiguous", timestamp_ms=int(time.time() * 1000),
                attempt_id=attempt_id, request_id=request_id,
                decision_event_id=decision_event_id, reason=f"tool exception: {type(error).__name__}",
            ))
            raise

        effect_status = result.effect_status
        if not result.success:
            if binding.metadata.failure_is_no_effect:
                effect_status = EffectStatus.NOT_APPLIED
            elif effect_status is EffectStatus.NOT_APPLIED:
                effect_status = EffectStatus.UNKNOWN
            elif effect_status is None:
                effect_status = EffectStatus.UNKNOWN
        recorded_result = ToolResult(result.success, result.tool, result.output, effect_status)
        try:
            self.memory.append(ResultEvent.from_tool_result(
                recorded_result, event_id=result_event_id, decision_event_id=decision_event_id,
                request_id=result_request_id, attempt_id=attempt_id,
            ))
        except Exception:
            # The external effect may already have happened. No rollback is claimed.
            try:
                self.memory.append(AttemptAmbiguousEvent(
                    event_id=f"{attempt_id}:ambiguous", timestamp_ms=int(time.time() * 1000),
                    attempt_id=attempt_id, request_id=request_id,
                    decision_event_id=decision_event_id,
                    reason="result persistence failed after dispatch; external effect unknown",
                ))
            except Exception:
                pass  # Durable IN_FLIGHT is conservatively recoverable as ambiguous.
            raise
        if not result.success and effect_status is not EffectStatus.NOT_APPLIED:
            self.memory.append(AttemptAmbiguousEvent(
                event_id=f"{attempt_id}:ambiguous", timestamp_ms=int(time.time() * 1000),
                attempt_id=attempt_id, request_id=request_id,
                decision_event_id=decision_event_id,
                reason="tool failure did not prove absence of external effect",
            ))
        return recorded_result
