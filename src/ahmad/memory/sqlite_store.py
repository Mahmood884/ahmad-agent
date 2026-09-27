"""Append-only SQLite WAL event store. Event payloads remain the source of truth."""

import json
import sqlite3
from pathlib import Path

from ahmad.core.events import DecisionEvent
from ahmad.core.results import ResultEvent


class SQLiteEventStore:
    def __init__(self, path: str | Path = "data/ahmad.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    timestamp_ms INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def append(self, event: DecisionEvent | ResultEvent) -> None:
        payload = event.to_dict()
        aggregate_id = (
            getattr(event, "request_id", None)
            or getattr(event, "decision_event_id", None)
            or event.event_id
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO events(event_id, timestamp_ms, event_type, aggregate_id, payload_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.timestamp_ms,
                    event.event_type.value,
                    aggregate_id,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                ),
            )

    def read(self, event_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM events WHERE event_id = ?", (event_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def read_stream(self, aggregate_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM events WHERE aggregate_id = ? ORDER BY sequence",
                (aggregate_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def read_all(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM events ORDER BY sequence"
            ).fetchall()
        return [json.loads(row[0]) for row in rows]
