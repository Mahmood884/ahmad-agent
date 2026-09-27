import json
from pathlib import Path
from typing import Protocol

from ahmad.core.events import DecisionEvent
from ahmad.core.results import ResultEvent


class EventStore(Protocol):
    def append(self, event: DecisionEvent | ResultEvent) -> None: ...

    def read_all(self) -> list[dict]: ...

    def read(self, event_id: str) -> dict | None: ...

    def read_stream(self, aggregate_id: str) -> list[dict]: ...


class MemoryStore:
    """
    سجل أحداث append-only — لا تعديل ولا حذف، فقط إضافة.
    الأحداث نفسها هي مصدر الحقيقة (event-sourced).
    ملاحظة: بدون قفل ملف — مفترض عملية وحدة (single-process) بالوقت الحالي.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: DecisionEvent | ResultEvent) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(event.to_json() + "\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def read(self, event_id: str) -> dict | None:
        return next((event for event in self.read_all() if event.get("event_id") == event_id), None)

    def read_stream(self, aggregate_id: str) -> list[dict]:
        return [
            event for event in self.read_all()
            if event.get("request_id") == aggregate_id
            or event.get("decision_event_id") == aggregate_id
            or event.get("event_id") == aggregate_id
        ]
