from dataclasses import asdict, dataclass
import json
import time
from typing import Protocol

from ahmad.core.events import EventType
from ahmad.core.types import EffectStatus


ResultEventType = EventType


class ToolResultLike(Protocol):
    success: bool
    tool: str
    output: str
    effect_status: EffectStatus | None


@dataclass(frozen=True)
class ResultEvent:
    event_id: str
    timestamp_ms: int
    event_type: ResultEventType
    decision_event_id: str
    success: bool
    tool: str
    output: str
    request_id: str
    attempt_id: str | None = None
    effect_status: EffectStatus | None = None

    @classmethod
    def from_tool_result(
        cls,
        result: ToolResultLike,
        *,
        event_id: str,
        decision_event_id: str,
        request_id: str,
        attempt_id: str | None = None,
        timestamp_ms: int | None = None,
    ) -> "ResultEvent":
        return cls(
            event_id=event_id,
            timestamp_ms=(
                int(time.time() * 1000)
                if timestamp_ms is None
                else timestamp_ms
            ),
            event_type=ResultEventType.RESULT,
            decision_event_id=decision_event_id,
            success=result.success,
            tool=result.tool,
            output=result.output,
            request_id=request_id,
            attempt_id=attempt_id,
            effect_status=getattr(result, "effect_status", None),
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        data["effect_status"] = (
            self.effect_status.value if self.effect_status is not None else None
        )
        if self.effect_status is None:
            data.pop("effect_status")
        if self.attempt_id is None:
            data.pop("attempt_id")
        return data

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
