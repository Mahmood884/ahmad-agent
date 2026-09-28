"""Evidence-driven ambiguity resolution; never executes a retry itself."""

import hashlib
import json
import time
from typing import Callable

from ahmad.core.attempts import AttemptCreatedEvent, IdempotencyEvidenceEvent, ReconcileEvidenceEvent
from ahmad.core.resolutions import ResolutionEvent
from ahmad.core.types import ReconcileOutcome, ResolutionPath, ResolutionResult
from ahmad.execution.registry import ToolBinding, ToolRegistry


def _reconcile_ambiguous(memory, registry: ToolRegistry, binding: ToolBinding,
                         attempt: dict, *, resolution_event_id: str,
                         invoke_reconciler: Callable[[str], object],
                         resolution_writer,
                         now_ms: int | None = None) -> ResolutionEvent | None:
    """Persist reconciler evidence before a resolution; called only by the Gateway."""
    _validate_ambiguous(memory, attempt, binding)
    contract = binding.metadata.reconcile_contract
    if not contract or not contract.available:
        return None
    if not registry.binding_is_current(binding):
        raise ValueError("binding changed since attempt; reconciliation rejected")
    try:
        raw = invoke_reconciler(attempt["idempotency_key"])
        outcome = raw if isinstance(raw, ReconcileOutcome) else ReconcileOutcome(str(raw).lower())
    except Exception:
        outcome = ReconcileOutcome.ERROR
    if not contract.authoritative:
        outcome = ReconcileOutcome.UNKNOWN
    timestamp = now_ms if now_ms is not None else int(time.time() * 1000)
    encoded = json.dumps({"outcome": outcome.value, "reconciler": contract.reconciler_id,
                          "version": contract.version}, sort_keys=True, separators=(",", ":"))
    evidence_id = f"{resolution_event_id}:evidence"
    evidence = ReconcileEvidenceEvent(
        event_id=evidence_id, timestamp_ms=timestamp, attempt_id=attempt["attempt_id"],
        request_id=attempt["request_id"], idempotency_key=attempt["idempotency_key"],
        binding_fingerprint=attempt["binding_fingerprint"], reconciler_id=contract.reconciler_id,
        reconciler_version=contract.version, outcome=outcome.value,
        evidence_ref=contract.evidence_ref, evidence_digest=hashlib.sha256(encoded.encode()).hexdigest(),
    )
    memory.append(evidence)
    if outcome not in {ReconcileOutcome.APPLIED, ReconcileOutcome.NOT_APPLIED}:
        return None
    result = (ResolutionResult.CONFIRMED_TERMINAL if outcome is ReconcileOutcome.APPLIED
              else ResolutionResult.CLEARED_FOR_RETRY)
    event = ResolutionEvent(
        event_id=resolution_event_id, timestamp_ms=timestamp, resolution_event_id=resolution_event_id,
        attempt_id=attempt["attempt_id"], ambiguous_event_id=attempt["ambiguous_event_id"],
        request_id=attempt["request_id"], original_decision_event_id=attempt["decision_event_id"],
        binding_fingerprint=attempt["binding_fingerprint"], idempotency_key=attempt["idempotency_key"],
        input_digest=attempt["input_digest"], resolution_result=result,
        resolution_path=ResolutionPath.RECONCILE_EVIDENCE, evidence_ref=contract.evidence_ref,
        reconcile_evidence_event_id=evidence_id,
        terminal_finding="applied" if outcome is ReconcileOutcome.APPLIED else "not_applied",
    )
    _append_resolution(resolution_writer, event)
    if result is ResolutionResult.CLEARED_FOR_RETRY:
        _create_retry_child(memory, attempt, event, timestamp)
    return event


def clear_for_idempotent_retry(memory, binding: ToolBinding, attempt: dict, *,
                               resolution_event_id: str, resolution_writer,
                               now_ms: int | None = None) -> ResolutionEvent:
    _validate_ambiguous(memory, attempt, binding)
    guarantee = binding.metadata.idempotency_guarantee
    if not guarantee or not registry_current(binding):
        raise ValueError("no current reviewed idempotency guarantee")
    if attempt["binding_fingerprint"] != binding.binding_id:
        raise ValueError("attempt binding mismatch")
    if attempt.get("guarantee_id") != guarantee.guarantee_id or attempt.get("guarantee_version") != guarantee.version:
        raise ValueError("attempt guarantee version mismatch")
    if (guarantee.input_matching_semantics != "canonical-json-sha256"
            or guarantee.binding_compatibility != "exact-binding"
            or guarantee.deduplication_enforcement != "tool-enforced-key"):
        raise ValueError("registered idempotency guarantee exceeds supported enforcement contract")
    canonical_input = json.dumps({"action": attempt["action"]}, sort_keys=True, separators=(",", ":"))
    if (attempt.get("canonicalization_version") != binding.metadata.canonicalization_version
            or attempt.get("input_digest") != hashlib.sha256(canonical_input.encode("utf-8")).hexdigest()):
        raise ValueError("idempotency input digest or canonicalization version mismatch")
    timestamp = now_ms if now_ms is not None else int(time.time() * 1000)
    created_at = attempt.get("created_at_ms", attempt.get("timestamp_ms"))
    if guarantee.retention_ms is not None and created_at is not None:
        if timestamp > created_at + guarantee.retention_ms:
            raise ValueError("idempotency guarantee retention has expired")
    valid_until = (created_at + guarantee.retention_ms
                   if guarantee.retention_ms is not None and created_at is not None else None)
    evidence = IdempotencyEvidenceEvent(
        event_id=f"{resolution_event_id}:evidence", timestamp_ms=timestamp,
        attempt_id=attempt["attempt_id"], request_id=attempt["request_id"],
        idempotency_key=attempt["idempotency_key"], idempotency_scope=attempt["idempotency_scope"],
        input_digest=attempt["input_digest"],
        binding_fingerprint=binding.binding_id, guarantee_id=guarantee.guarantee_id,
        guarantee_version=guarantee.version, evidence_ref=guarantee.contract_evidence_ref,
        valid_until_ms=valid_until,
    )
    memory.append(evidence)
    event = ResolutionEvent(
        event_id=resolution_event_id, timestamp_ms=timestamp, resolution_event_id=resolution_event_id,
        attempt_id=attempt["attempt_id"], ambiguous_event_id=attempt["ambiguous_event_id"],
        request_id=attempt["request_id"], original_decision_event_id=attempt["decision_event_id"],
        binding_fingerprint=binding.binding_id, idempotency_key=attempt["idempotency_key"],
        input_digest=attempt["input_digest"], resolution_result=ResolutionResult.CLEARED_FOR_RETRY,
        resolution_path=ResolutionPath.IDEMPOTENT_RETRY, evidence_ref=guarantee.contract_evidence_ref,
        guarantee_id=guarantee.guarantee_id, guarantee_version=guarantee.version,
    )
    _append_resolution(resolution_writer, event)
    _create_retry_child(memory, attempt, event, timestamp)
    return event


def _create_retry_child(memory, attempt: dict, resolution: ResolutionEvent, timestamp: int) -> None:
    child_id = f"{attempt['attempt_id']}:retry:{resolution.resolution_event_id}"
    child = AttemptCreatedEvent(
        event_id=f"{child_id}:created", timestamp_ms=timestamp, attempt_id=child_id,
        request_id=attempt["request_id"], action=attempt["action"], mode=attempt["mode"],
        scope=attempt["scope"], binding_fingerprint=attempt["binding_fingerprint"],
        idempotency_key=attempt["idempotency_key"], idempotency_scope=attempt["idempotency_scope"],
        input_digest=attempt["input_digest"], canonicalization_version=attempt["canonicalization_version"],
        guarantee_id=attempt.get("guarantee_id"), guarantee_version=attempt.get("guarantee_version"),
        decision_event_id=None, root_attempt_id=attempt.get("root_attempt_id") or attempt["attempt_id"],
        resolved_from_resolution_event_id=resolution.resolution_event_id,
        registry_manifest_json=attempt.get("registry_manifest_json", "{}"),
    )
    claims = (("attempt_id", child_id, child_id),
              ("resolution_child", resolution.resolution_event_id, child_id))
    append_claims = getattr(memory, "append_with_claims", None)
    if append_claims:
        append_claims(child, claims)
    else:
        memory.append(child)


def registry_current(binding: ToolBinding) -> bool:
    return ToolRegistry.binding_is_current(binding)


def _manual_reconcile(memory, binding: ToolBinding, attempt: dict, *,
                     resolution_event_id: str, evidence_ref: str, evidence: str,
                     authorize: Callable[[dict], tuple[str, str]] | None,
                     resolution_writer,
                     result: ResolutionResult, terminal_finding: str | None = None,
                     now_ms: int | None = None) -> ResolutionEvent:
    """Manual resolution is deny-by-default and requires trusted identity + policy event."""
    _validate_ambiguous(memory, attempt, binding)
    if not registry_current(binding):
        raise ValueError("binding changed since attempt; manual reconciliation rejected")
    if authorize is None:
        raise PermissionError("manual reconciliation is disabled without governance authorization")
    resolved_by, decision_id = authorize(attempt)
    auth = memory.read(decision_id)
    if (not resolved_by or not auth or auth.get("event_type") != "decision"
            or auth.get("request_id") != attempt["request_id"]
            or auth.get("action") != "manual:reconcile"
            or auth.get("scope") != attempt.get("scope")
            or auth.get("tool_binding_id") != binding.binding_id
            or auth.get("allowed") is not True):
        raise PermissionError("manual reconciliation lacks a matching PolicyEngine DecisionEvent")
    timestamp = now_ms if now_ms is not None else int(time.time() * 1000)
    evidence_event = ReconcileEvidenceEvent(
        event_id=f"{resolution_event_id}:evidence", timestamp_ms=timestamp,
        attempt_id=attempt["attempt_id"], request_id=attempt["request_id"],
        idempotency_key=attempt["idempotency_key"], binding_fingerprint=binding.binding_id,
        reconciler_id=f"operator:{resolved_by}", reconciler_version="manual-v1",
        outcome=terminal_finding or "unknown", evidence_ref=evidence_ref,
        evidence_digest=hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
    )
    memory.append(evidence_event)
    event = ResolutionEvent(
        event_id=resolution_event_id, timestamp_ms=timestamp,
        resolution_event_id=resolution_event_id, attempt_id=attempt["attempt_id"],
        ambiguous_event_id=attempt["ambiguous_event_id"], request_id=attempt["request_id"],
        original_decision_event_id=attempt["decision_event_id"],
        binding_fingerprint=binding.binding_id, idempotency_key=attempt["idempotency_key"],
        input_digest=attempt["input_digest"], resolution_result=result,
        resolution_path=ResolutionPath.MANUAL_RECONCILIATION, evidence_ref=evidence_ref,
        resolved_by=resolved_by, manual_authorization_decision_id=decision_id,
        terminal_finding=terminal_finding if result is ResolutionResult.CONFIRMED_TERMINAL else None,
    )
    _append_resolution(resolution_writer, event)
    if result is ResolutionResult.CLEARED_FOR_RETRY:
        _create_retry_child(memory, attempt, event, timestamp)
    return event


def _validate_ambiguous(memory, attempt: dict, binding: ToolBinding) -> None:
    events = memory.read_all()
    created = next((e for e in events if e.get("event_type") == "attempt_created"
                    and e.get("attempt_id") == attempt.get("attempt_id")), None)
    ambiguous = next((e for e in events if e.get("event_type") == "attempt_ambiguous"
                      and e.get("attempt_id") == attempt.get("attempt_id")), None)
    if not created or not ambiguous:
        raise ValueError("attempt is not durably ambiguous")
    if (created.get("request_id") != attempt.get("request_id")
            or created.get("action") != attempt.get("action")
            or created.get("mode") != attempt.get("mode")
            or created.get("scope") != attempt.get("scope")
            or created.get("decision_event_id") != attempt.get("decision_event_id")
            or created.get("binding_fingerprint") != binding.binding_id
            or created.get("registry_manifest_json") != binding.manifest_json
            or created.get("idempotency_key") != attempt.get("idempotency_key")
            or created.get("input_digest") != attempt.get("input_digest")
            or attempt.get("binding_fingerprint") != binding.binding_id
            or ambiguous.get("event_id") != attempt.get("ambiguous_event_id")):
        raise ValueError("attempt, ambiguity, decision, or binding correlation mismatch")
    decision = memory.read(attempt["decision_event_id"])
    if (not decision or decision.get("request_id") != attempt.get("request_id")
            or decision.get("tool_binding_id") != binding.binding_id
            or decision.get("action") != attempt.get("action")
            or decision.get("mode") != attempt.get("mode")
            or decision.get("scope") != attempt.get("scope")
            or decision.get("allowed") is not True):
        raise ValueError("attempt decision event does not match")


def _append_resolution(writer, event: ResolutionEvent) -> None:
    writer.append(event)


def validate_retry_authority(memory, child: dict, binding: ToolBinding, *, now_ms: int) -> bool:
    """Revalidate a child against its immutable resolution, evidence and current contract."""
    events = memory.read_all()
    resolution_id = child.get("resolved_from_resolution_event_id")
    resolution = next((e for e in events if e.get("event_type") == "resolution"
                       and e.get("resolution_event_id") == resolution_id), None)
    if not resolution or resolution.get("resolution_result") != "cleared_for_retry":
        return False
    from ahmad.memory.attempt_projection import AttemptProjection

    root = AttemptProjection(events).attempts().get(resolution.get("attempt_id"))
    if not root:
        return False
    try:
        _validate_ambiguous(memory, root, binding)
    except (KeyError, ValueError):
        return False
    if (resolution.get("request_id") != child.get("request_id")
            or resolution.get("original_decision_event_id") != root.get("decision_event_id")
            or resolution.get("ambiguous_event_id") != root.get("ambiguous_event_id")
            or resolution.get("binding_fingerprint") != binding.binding_id
            or resolution.get("idempotency_key") != child.get("idempotency_key")
            or resolution.get("input_digest") != child.get("input_digest")
            or child.get("binding_fingerprint") != binding.binding_id
            or child.get("registry_manifest_json") != binding.manifest_json
            or child.get("guarantee_id") != root.get("guarantee_id")
            or child.get("guarantee_version") != root.get("guarantee_version")):
        return False
    path = resolution.get("resolution_path")
    evidence = memory.read(f"{resolution_id}:evidence")
    if not evidence or evidence.get("attempt_id") != root["attempt_id"] \
            or evidence.get("request_id") != root["request_id"] \
            or evidence.get("binding_fingerprint") != binding.binding_id \
            or evidence.get("evidence_ref") != resolution.get("evidence_ref"):
        return False
    if path == ResolutionPath.RECONCILE_EVIDENCE.value:
        contract = binding.metadata.reconcile_contract
        expected = "not_applied"
        expected_digest = hashlib.sha256(json.dumps(
            {"outcome": "not_applied", "reconciler": contract.reconciler_id,
             "version": contract.version}, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest() if contract else None
        return bool(contract and contract.available and contract.authoritative
                    and evidence.get("reconciler_id") == contract.reconciler_id
                    and evidence.get("reconciler_version") == contract.version
                    and evidence.get("outcome") == expected
                    and evidence.get("evidence_digest") == expected_digest
                    and resolution.get("reconcile_evidence_event_id") == evidence.get("event_id"))
    if path == ResolutionPath.IDEMPOTENT_RETRY.value:
        guarantee = binding.metadata.idempotency_guarantee
        return bool(guarantee and guarantee.guarantee_id == resolution.get("guarantee_id")
                    and guarantee.version == resolution.get("guarantee_version")
                    and evidence.get("guarantee_id") == guarantee.guarantee_id
                    and evidence.get("guarantee_version") == guarantee.version
                    and evidence.get("idempotency_key") == child.get("idempotency_key")
                    and evidence.get("idempotency_scope") == child.get("idempotency_scope")
                    and evidence.get("input_digest") == child.get("input_digest")
                    and evidence.get("evidence_ref") == guarantee.contract_evidence_ref
                    and (evidence.get("valid_until_ms") is None
                         or now_ms <= evidence["valid_until_ms"]))
    if path == ResolutionPath.MANUAL_RECONCILIATION.value:
        auth = memory.read(resolution.get("manual_authorization_decision_id", ""))
        return bool(resolution.get("resolved_by") and auth
                    and auth.get("event_type") == "decision" and auth.get("allowed") is True
                    and auth.get("action") == "manual:reconcile"
                    and auth.get("request_id") == child.get("request_id"))
    return False
