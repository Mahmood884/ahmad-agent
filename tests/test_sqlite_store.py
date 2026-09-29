import pytest

from ahmad.core.events import DecisionEvent
from ahmad.core.types import Mode, Scope
from ahmad.governance.policy import PolicyEngine
from ahmad.memory.sqlite_encryption import require_sqlcipher
from ahmad.memory.sqlite_store import SQLiteEventStore


def test_sqlite_store_uses_wal_and_reads_event_stream(tmp_path):
    store = SQLiteEventStore(tmp_path / "ahmad.db")
    decision = PolicyEngine().evaluate("demo:mock", Mode.GENERAL, Scope.PERSONAL)
    event = DecisionEvent.from_decision(
        decision, event_id="decision-1", request_id="request-1", timestamp_ms=10
    )
    store.append(event)

    with store._connect() as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal_mode.lower() == "wal"
    assert store.read("decision-1") == event.to_dict()
    assert store.read_stream("request-1") == [event.to_dict()]


def test_sqlite_store_rejects_duplicate_event_ids(tmp_path):
    store = SQLiteEventStore(tmp_path / "ahmad.db")
    decision = PolicyEngine().evaluate("no", Mode.GENERAL, Scope.PERSONAL)
    event = DecisionEvent.from_decision(
        decision, event_id="same", request_id="request-same", timestamp_ms=1
    )
    store.append(event)
    with pytest.raises(require_sqlcipher().IntegrityError):
        store.append(event)
