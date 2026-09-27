from dataclasses import asdict, dataclass
from enum import Enum
import json
import time

from ahmad.execution.mock_tool import ToolResult


class ResultEventType(str, Enum):
    RESULT = "result"


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

    @classmethod
    def from_tool_result(
        cls,
        result: ToolResult,
        *,
        event_id: str,
        decision_event_id: str,
        request_id: str,
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
