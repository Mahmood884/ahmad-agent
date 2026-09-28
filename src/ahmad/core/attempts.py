"""Immutable event records for a single governed execution attempt."""

from dataclasses import asdict, dataclass
from typing import Any

from ahmad.core.events import EventType
from ahmad.core.types import AttemptState, EffectStatus


@dataclass(frozen=True)
class AttemptCreatedEvent:
    event_id: str
    timestamp_ms: int
    attempt_id: str
    request_id: str
    action: str
    mode: str
    scope: str
    binding_fingerprint: str
    idempotency_key: str
    idempotency_scope: str
    input_digest: str
    canonicalization_version: str
    guarantee_id: str | None = None
    guarantee_version: str | None = None
    state: AttemptState = AttemptState.PENDING
    decision_event_id: str | None = None
    root_attempt_id: str | None = None
    resolved_from_resolution_event_id: str | None = None
    registry_manifest_json: str = "{}"

    def __post_init__(self) -> None:
        if self.state is not AttemptState.PENDING:
            raise ValueError("AttemptCreatedEvent must start in PENDING")
        if not all((self.event_id, self.attempt_id, self.request_id, self.action,
                    self.binding_fingerprint, self.idempotency_key, self.idempotency_scope,
                    self.input_digest, self.canonicalization_version)):
            raise ValueError("AttemptCreatedEvent correlation fields are required")

    @property
    def event_type(self) -> EventType:
        return EventType.ATTEMPT_CREATED

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        data["state"] = self.state.value
        return data

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class AttemptStartedEvent:
    event_id: str
    timestamp_ms: int
    attempt_id: str
    request_id: str
    decision_event_id: str
    binding_fingerprint: str
    lease_id: str
    state: AttemptState = AttemptState.IN_FLIGHT

    def __post_init__(self) -> None:
        if self.state is not AttemptState.IN_FLIGHT:
            raise ValueError("AttemptStartedEvent state must be IN_FLIGHT")

    @property
    def event_type(self) -> EventType:
        return EventType.ATTEMPT_STARTED

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        data["state"] = self.state.value
        return data

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class AttemptAmbiguousEvent:
    event_id: str
    timestamp_ms: int
    attempt_id: str
    request_id: str
    decision_event_id: str
    reason: str
    state: AttemptState = AttemptState.AMBIGUOUS

    def __post_init__(self) -> None:
        if self.state is not AttemptState.AMBIGUOUS:
            raise ValueError("AttemptAmbiguousEvent state must be AMBIGUOUS")

    @property
    def event_type(self) -> EventType:
        return EventType.ATTEMPT_AMBIGUOUS

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        data["state"] = self.state.value
        return data

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class AttemptDecisionLinkedEvent:
    event_id: str
    timestamp_ms: int
    attempt_id: str
    request_id: str
    decision_event_id: str

    @property
    def event_type(self) -> EventType:
        return EventType.ATTEMPT_DECISION_LINKED

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        return data

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ReconcileEvidenceEvent:
    event_id: str
    timestamp_ms: int
    attempt_id: str
    request_id: str
    idempotency_key: str
    binding_fingerprint: str
    reconciler_id: str
    reconciler_version: str
    outcome: str
    evidence_ref: str
    evidence_digest: str

    @property
    def event_type(self) -> EventType:
        return EventType.RECONCILE_EVIDENCE

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        return data

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class IdempotencyEvidenceEvent:
    event_id: str
    timestamp_ms: int
    attempt_id: str
    request_id: str
    idempotency_key: str
    idempotency_scope: str
    input_digest: str
    binding_fingerprint: str
    guarantee_id: str
    guarantee_version: str
    evidence_ref: str
    valid_until_ms: int | None

    @property
    def event_type(self) -> EventType:
        return EventType.IDEMPOTENCY_EVIDENCE

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        return data

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
