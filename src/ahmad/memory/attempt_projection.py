"""Deterministic, rebuildable attempt and resolution audit views."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AttentionItem:
    kind: str
    reference_id: str
    reason: str


class AttemptProjection:
    def __init__(self, events: list[dict[str, Any]]):
        self.events = events

    def attempts(self) -> dict[str, dict[str, Any]]:
        attempts: dict[str, dict[str, Any]] = {}
        for event in self.events:
            kind = event.get("event_type")
            attempt_id = event.get("attempt_id")
            if not attempt_id:
                continue
            row = attempts.setdefault(attempt_id, {"attempt_id": attempt_id, "state": None})
            if kind == "attempt_created":
                row.update(event)
                row["created_at_ms"] = event.get("timestamp_ms")
                row["state"] = "pending"
            elif kind == "attempt_started":
                row.update(event)
                row["state"] = "in_flight"
            elif kind == "attempt_ambiguous":
                row.update(event)
                row["state"] = "ambiguous"
                row["ambiguous_event_id"] = event.get("event_id")
            elif kind == "attempt_decision_linked":
                row["decision_event_id"] = event.get("decision_event_id")
            elif kind == "result":
                row["outcome"] = "succeeded" if event.get("success") else (
                    "failed_clean" if event.get("effect_status") == "not_applied" else "ambiguous"
                )
        return attempts

    def attention_required(self, *, now_ms: int, linkage_sla_ms: int) -> list[AttentionItem]:
        if linkage_sla_ms < 0:
            raise ValueError("linkage_sla_ms must be non-negative")
        attempts = self.attempts()
        resolutions = [e for e in self.events if e.get("event_type") == "resolution"
                       and e.get("resolution_result") == "cleared_for_retry"]
        result: list[AttentionItem] = []
        children = {e.get("resolved_from_resolution_event_id") for e in self.events
                    if e.get("event_type") == "attempt_created"}
        for resolution in resolutions:
            resolution_id = resolution.get("resolution_event_id")
            if resolution_id not in children and now_ms - resolution.get("timestamp_ms", now_ms) >= linkage_sla_ms:
                result.append(AttentionItem("missing_retry_child", resolution_id or "",
                                            "CLEARED_FOR_RETRY has no child attempt after SLA"))
        for attempt_id, attempt in attempts.items():
            decision_id = attempt.get("decision_event_id")
            decision_exists = any(event.get("event_type") == "decision"
                                  and event.get("event_id") == decision_id for event in self.events)
            if attempt.get("resolved_from_resolution_event_id") and not decision_exists:
                created = attempt.get("created_at_ms", now_ms)
                if now_ms - created >= linkage_sla_ms:
                    result.append(AttentionItem("missing_retry_decision", attempt_id,
                                                "retry child has no linked DecisionEvent after SLA"))
        return result

    def recover_in_flight(self, memory, *, now_ms: int) -> int:
        """Conservatively convert orphaned IN_FLIGHT attempts to AMBIGUOUS."""
        count = 0
        for attempt_id, attempt in self.attempts().items():
            if attempt.get("state") != "in_flight" or attempt.get("outcome") in {"succeeded", "failed_clean"}:
                continue
            event_id = f"{attempt_id}:ambiguous:recovery"
            if any(event.get("event_id") == event_id for event in self.events) or memory.read(event_id):
                continue
            from ahmad.core.attempts import AttemptAmbiguousEvent

            memory.append(AttemptAmbiguousEvent(
                event_id=event_id, timestamp_ms=now_ms, attempt_id=attempt_id,
                request_id=attempt["request_id"],
                decision_event_id=attempt["decision_event_id"],
                reason="orphaned IN_FLIGHT found during recovery; external effect unknown",
            ))
            count += 1
        return count
