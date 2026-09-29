"""Append-only SQLite WAL event store with durable uniqueness claims."""

import json
from pathlib import Path
from typing import Any

from ahmad.memory.sqlite_encryption import connect_encrypted, load_encryption_key
from ahmad.memory.store import _RESOLUTION_WRITE_TOKEN, _event_type_value


class SQLiteEventStore:
    def __init__(
        self,
        path: str | Path = "data/ahmad.db",
        *,
        key_path: str | Path | None = None,
    ) -> None:
        self.path = Path(path)
        self._key = load_encryption_key(key_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                timestamp_ms INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                aggregate_id TEXT NOT NULL,
                payload_json TEXT NOT NULL)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS event_claims (
                namespace TEXT NOT NULL,
                claim_key TEXT NOT NULL,
                claim_value TEXT NOT NULL,
                event_id TEXT NOT NULL,
                PRIMARY KEY(namespace, claim_key),
                FOREIGN KEY(event_id) REFERENCES events(event_id))""")

    def _connect(self) -> Any:
        connection = connect_encrypted(self.path, self._key, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def append(self, event: Any) -> None:
        self.append_with_claims(event, ())

    def append_with_claims(self, event: Any, claims: tuple[tuple[str, str, str], ...]) -> None:
        if _event_type_value(event) == "resolution":
            raise PermissionError("ResolutionEvent requires the Gateway resolution writer")
        self._append(event, claims)

    def _append_resolution(self, event: Any, *, authority: object) -> None:
        if authority is not _RESOLUTION_WRITE_TOKEN:
            raise PermissionError("invalid ResolutionEvent writer capability")
        if _event_type_value(event) != "resolution":
            raise ValueError("trusted resolution writer accepts ResolutionEvent only")
        self._append(event, ())

    def _append(self, event: Any, claims: tuple[tuple[str, str, str], ...]) -> None:
        payload = event.to_dict()
        aggregate_id = (getattr(event, "request_id", None)
                        or getattr(event, "decision_event_id", None)
                        or getattr(event, "attempt_id", None)
                        or event.event_id)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO events(event_id,timestamp_ms,event_type,aggregate_id,payload_json) VALUES(?,?,?,?,?)",
                (event.event_id, event.timestamp_ms, event.event_type.value, aggregate_id,
                 json.dumps(payload, sort_keys=True, separators=(",", ":"))),
            )
            combined = {(ns, key): value for ns, key, value in _inferred_claims(event)}
            for namespace, claim_key, claim_value in claims:
                old_value = combined.get((namespace, claim_key))
                if old_value is not None and old_value != claim_value:
                    raise ValueError(f"conflicting {namespace} claim: {claim_key}")
                combined[(namespace, claim_key)] = claim_value
            for (namespace, claim_key), claim_value in combined.items():
                existing = connection.execute(
                    "SELECT claim_value FROM event_claims WHERE namespace=? AND claim_key=?",
                    (namespace, claim_key),
                ).fetchone()
                if existing and namespace in {"attempt_id", "resolution_child", "attempt_resolution"}:
                    raise ValueError(f"duplicate {namespace} claim: {claim_key}")
                if existing and existing[0] != claim_value:
                    raise ValueError(f"conflicting {namespace} claim: {claim_key}")
                if not existing:
                    connection.execute(
                        "INSERT INTO event_claims VALUES(?,?,?,?)",
                        (namespace, claim_key, claim_value, event.event_id),
                    )

    def claim(self, namespace: str, claim_key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT claim_value FROM event_claims WHERE namespace=? AND claim_key=?",
                (namespace, claim_key),
            ).fetchone()
        return row[0] if row else None

    def read(self, event_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload_json FROM events WHERE event_id=?", (event_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def read_stream(self, aggregate_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM events WHERE aggregate_id=? ORDER BY sequence", (aggregate_id,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def read_all(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload_json FROM events ORDER BY sequence").fetchall()
        return [json.loads(row[0]) for row in rows]


def _idempotency_claim_value(event: dict) -> str:
    return "|".join((event.get("root_attempt_id") or event.get("attempt_id", ""),
                     event.get("input_digest", ""), event.get("binding_fingerprint", ""),
                     event.get("guarantee_id") or "", event.get("guarantee_version") or ""))


def _inferred_claims(event: Any) -> tuple[tuple[str, str, str], ...]:
    data = event.to_dict()
    kind = data.get("event_type")
    if kind == "attempt_created":
        claims = [("attempt_id", data["attempt_id"], data["attempt_id"])]
        claims.append(("idempotency", f"{data['idempotency_scope']}:{data['idempotency_key']}",
                       _idempotency_claim_value(data)))
        if data.get("resolved_from_resolution_event_id"):
            claims.append(("resolution_child", data["resolved_from_resolution_event_id"], data["attempt_id"]))
        return tuple(claims)
    if kind == "resolution":
        return (("attempt_resolution", data["attempt_id"], data["resolution_event_id"]),)
    return ()
