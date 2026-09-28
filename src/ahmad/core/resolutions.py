"""Immutable ambiguity-resolution event records."""

from dataclasses import asdict, dataclass
import json
from typing import Any

from ahmad.core.events import EventType
from ahmad.core.types import ResolutionPath, ResolutionResult


@dataclass(frozen=True)
class ResolutionEvent:
    event_id: str
    timestamp_ms: int
    resolution_event_id: str
    attempt_id: str
    ambiguous_event_id: str
    request_id: str
    original_decision_event_id: str
    binding_fingerprint: str
    idempotency_key: str
    input_digest: str
    resolution_result: ResolutionResult
    resolution_path: ResolutionPath
    evidence_ref: str
    guarantee_id: str | None = None
    guarantee_version: str | None = None
    reconcile_evidence_event_id: str | None = None
    resolved_by: str | None = None
    manual_authorization_decision_id: str | None = None
    terminal_finding: str | None = None
    authorized_new_attempt_id: str | None = None

    @property
    def event_type(self) -> EventType:
        return EventType.RESOLUTION

    def __post_init__(self) -> None:
        if not self.evidence_ref.strip():
            raise ValueError("evidence_ref is required")
        if self.resolution_path is ResolutionPath.RECONCILE_EVIDENCE:
            if not self.reconcile_evidence_event_id:
                raise ValueError("reconcile evidence event is required")
        if self.resolution_path is ResolutionPath.IDEMPOTENT_RETRY:
            if not self.guarantee_id or not self.guarantee_version:
                raise ValueError("idempotency guarantee identity is required")
            if self.resolution_result is not ResolutionResult.CLEARED_FOR_RETRY:
                raise ValueError("idempotent retry must clear for retry")
        if self.resolution_path is ResolutionPath.MANUAL_RECONCILIATION:
            if not self.resolved_by or not self.manual_authorization_decision_id:
                raise ValueError("authorized manual identity is required")
        if self.resolution_result is ResolutionResult.CONFIRMED_TERMINAL:
            if self.terminal_finding not in {"applied", "not_applied"}:
                raise ValueError("terminal resolution requires a confirmed finding")
        if self.resolution_result is ResolutionResult.CLEARED_FOR_RETRY and self.authorized_new_attempt_id:
            raise ValueError("forward linkage belongs on the child Attempt")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        data["resolution_path"] = self.resolution_path.value
        data["resolution_result"] = self.resolution_result.value
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
