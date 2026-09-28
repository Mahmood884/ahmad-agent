import json
import os
from pathlib import Path
from threading import RLock
from typing import Any
from typing import Protocol

from ahmad.core.events import DecisionEvent
from ahmad.core.results import ResultEvent


_RESOLUTION_WRITE_TOKEN = object()


class _TrustedResolutionWriter:
    """Narrow in-process capability used only by Gateway-owned resolution flows."""

    def __init__(self, store: Any, token: object):
        self.__store = store
        self.__token = token

    def append(self, event: Any) -> None:
        self.__store._append_resolution(event, authority=self.__token)


def _resolution_writer_for(store: Any) -> _TrustedResolutionWriter:
    return _TrustedResolutionWriter(store, _RESOLUTION_WRITE_TOKEN)


def _event_type_value(event: Any) -> str | None:
    value = getattr(event, "event_type", None)
    return getattr(value, "value", value)


class EventStore(Protocol):
    def append(self, event: Any) -> None: ...

    def append_with_claims(self, event: Any, claims: tuple[tuple[str, str, str], ...]) -> None: ...

    def _append_resolution(self, event: Any, *, authority: object) -> None: ...

    def claim(self, namespace: str, claim_key: str) -> str | None: ...

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
        self._lock = RLock()

    def append(self, event: Any) -> None:
        self.append_with_claims(event, ())

    def append_with_claims(self, event: Any, claims: tuple[tuple[str, str, str], ...]) -> None:
        # JSONL is a single-process adapter. Claims are reconstructed from the
        # immutable records; cross-process uniqueness requires SQLite.
        if _event_type_value(event) == "resolution":
            raise PermissionError("ResolutionEvent requires the Gateway resolution writer")
        with self._lock:
            if self.read(event.event_id) is not None:
                raise ValueError(f"duplicate event_id: {event.event_id}")
            combined = {(ns, key): value for ns, key, value in _inferred_claims(event)}
            for namespace, key, value in claims:
                old_value = combined.get((namespace, key))
                if old_value is not None and old_value != value:
                    raise ValueError(f"conflicting {namespace} claim: {key}")
                combined[(namespace, key)] = value
            for (namespace, key), value in combined.items():
                old = self.claim(namespace, key)
                if old is not None and namespace in {"attempt_id", "resolution_child", "attempt_resolution"}:
                    raise ValueError(f"duplicate {namespace} claim: {key}")
                if old is not None and old != value:
                    raise ValueError(f"conflicting {namespace} claim: {key}")
            with self.path.open("a", encoding="utf-8") as f:
                f.write(event.to_json() + "\n")
                f.flush()
                os.fsync(f.fileno())

    def _append_resolution(self, event: Any, *, authority: object) -> None:
        if authority is not _RESOLUTION_WRITE_TOKEN:
            raise PermissionError("invalid ResolutionEvent writer capability")
        if _event_type_value(event) != "resolution":
            raise ValueError("trusted resolution writer accepts ResolutionEvent only")
        with self._lock:
            if self.read(event.event_id) is not None:
                raise ValueError(f"duplicate event_id: {event.event_id}")
            for namespace, key, value in _inferred_claims(event):
                old = self.claim(namespace, key)
                if old is not None and namespace in {"attempt_id", "resolution_child", "attempt_resolution"}:
                    raise ValueError(f"duplicate {namespace} claim: {key}")
                if old is not None and old != value:
                    raise ValueError(f"conflicting {namespace} claim: {key}")
            with self.path.open("a", encoding="utf-8") as f:
                f.write(event.to_json() + "\n")
                f.flush()
                os.fsync(f.fileno())

    def claim(self, namespace: str, claim_key: str) -> str | None:
        for event in self.read_all():
            if namespace == "attempt_id" and event.get("attempt_id") == claim_key:
                return event.get("attempt_id")
            if namespace == "resolution_child" and event.get("resolved_from_resolution_event_id") == claim_key:
                return event.get("attempt_id")
            if namespace == "attempt_resolution" and event.get("event_type") == "resolution" and event.get("attempt_id") == claim_key:
                return event.get("resolution_event_id")
            if namespace == "idempotency":
                key = f"{event.get('idempotency_scope')}:{event.get('idempotency_key')}"
                if event.get("event_type") == "attempt_created" and key == claim_key:
                    return _idempotency_claim_value(event)
        return None
    def read_all(self) -> list[dict]:
        """يقرأ كل الأحداث. يتجاهل الأسطر المكسورة (graceful degradation)."""
        if not self.path.exists():
            return []
        events: list[dict] = []
        with self.path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    import logging
                    logging.getLogger(__name__).warning(
                        "Skipping corrupted JSONL line %d in %s: %s",
                        line_no, self.path, exc,
                    )
                    continue
        return events

    def read(self, event_id: str) -> dict | None:
        return next((event for event in self.read_all() if event.get("event_id") == event_id), None)

    def read_stream(self, aggregate_id: str) -> list[dict]:
        return [
            event for event in self.read_all()
            if event.get("request_id") == aggregate_id
            or event.get("decision_event_id") == aggregate_id
            or event.get("event_id") == aggregate_id
        ]


def _idempotency_claim_value(event: dict) -> str:
    return "|".join((event.get("root_attempt_id") or event.get("attempt_id", ""),
                     event.get("input_digest", ""), event.get("binding_fingerprint", ""),
                     event.get("guarantee_id") or "", event.get("guarantee_version") or ""))


def _inferred_claims(event: Any) -> tuple[tuple[str, str, str], ...]:
    data = event.to_dict()
    kind = data.get("event_type")
    if kind == "attempt_created":
        claims = [("attempt_id", data["attempt_id"], data["attempt_id"])]
        key = f"{data['idempotency_scope']}:{data['idempotency_key']}"
        claims.append(("idempotency", key, _idempotency_claim_value(data)))
        if data.get("resolved_from_resolution_event_id"):
            claims.append(("resolution_child", data["resolved_from_resolution_event_id"], data["attempt_id"]))
        return tuple(claims)
    if kind == "resolution":
        return (("attempt_resolution", data["attempt_id"], data["resolution_event_id"]),)
    return ()
