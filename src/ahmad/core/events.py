from dataclasses import asdict, dataclass
from enum import Enum
import json
import time

from ahmad.core.types import Decision


class EventType(str, Enum):
    DECISION = "decision"
    RESULT = "result"
    ATTEMPT_CREATED = "attempt_created"
    ATTEMPT_STARTED = "attempt_started"
    ATTEMPT_AMBIGUOUS = "attempt_ambiguous"
    ATTEMPT_DECISION_LINKED = "attempt_decision_linked"
    RECONCILE_EVIDENCE = "reconcile_evidence"
    IDEMPOTENCY_EVIDENCE = "idempotency_evidence"
    RESOLUTION = "resolution"
    REGISTRY_MANIFEST = "registry_manifest"


@dataclass(frozen=True)
class DecisionEvent:
    event_id: str
    timestamp_ms: int
    event_type: EventType
    action: str
    mode: str
    scope: str
    allowed: bool
    reason: str
    request_id: str
    source: str | None = None
    tool_binding_id: str | None = None
    network_approved: bool = False

    @property
    def binding_fingerprint(self) -> str | None:
        """The current binding identity includes its implementation fingerprint."""
        return self.tool_binding_id

    @classmethod
    def from_decision(
        cls,
        decision: Decision,
        *,
        event_id: str,
        request_id: str,
        source: str | None = None,
        timestamp_ms: int | None = None,
    ) -> "DecisionEvent":
        return cls(
            event_id=event_id,
            timestamp_ms=(
                int(time.time() * 1000)
                if timestamp_ms is None
                else timestamp_ms
            ),
            event_type=EventType.DECISION,
            action=decision.action,
            mode=decision.mode.value,
            scope=decision.scope.value,
            allowed=decision.allowed,
            reason=decision.reason,
            request_id=request_id,
            source=decision.source if source is None else source,
            tool_binding_id=decision.tool_binding_id,
            network_approved=decision.network_approved,
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        if self.source is None:
            data.pop("source")
        if self.tool_binding_id is None:
            data.pop("tool_binding_id")
        if not self.network_approved:
            data.pop("network_approved")
        return data

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
