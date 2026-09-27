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

    @classmethod
    def from_decision(
        cls,
        decision: Decision,
        *,
        event_id: str,
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
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        return data

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
