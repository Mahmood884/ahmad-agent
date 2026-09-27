from dataclasses import asdict, dataclass
from enum import Enum
import json
import time

from ahmad.core.types import Decision


class EventType(str, Enum):
    DECISION = "decision"


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
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        if self.source is None:
            data.pop("source")
        if self.tool_binding_id is None:
            data.pop("tool_binding_id")
        return data

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
