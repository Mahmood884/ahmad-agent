"""Rebuildable in-memory views derived from immutable event records."""

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class DecisionProjection:
    decisions: dict[str, dict] = field(default_factory=dict)

    def apply(self, event: dict) -> None:
        if event.get("event_type") == "decision":
            self.decisions[event["event_id"]] = dict(event)

    def rebuild(self, events: Iterable[dict]) -> None:
        self.decisions.clear()
        for event in events:
            self.apply(event)


@dataclass
class ToolUsageProjection:
    counts: Counter = field(default_factory=Counter)

    def apply(self, event: dict) -> None:
        if event.get("event_type") == "result":
            self.counts[(event.get("tool", "unknown"), bool(event.get("success")))] += 1

    def rebuild(self, events: Iterable[dict]) -> None:
        self.counts.clear()
        for event in events:
            self.apply(event)


@dataclass
class RuntimeStateProjection:
    latest_by_request: dict[str, dict] = field(default_factory=dict)

    def apply(self, event: dict) -> None:
        request_id = event.get("request_id")
        if request_id:
            self.latest_by_request[request_id] = dict(event)

    def rebuild(self, events: Iterable[dict]) -> None:
        self.latest_by_request.clear()
        for event in events:
            self.apply(event)
