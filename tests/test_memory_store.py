import json

from ahmad.core.events import DecisionEvent
from ahmad.core.types import Mode, Scope
from ahmad.governance.policy import PolicyEngine
from ahmad.memory.store import MemoryStore


def make_event(action: str, event_id: str) -> DecisionEvent:
    policy = PolicyEngine()

    decision = policy.evaluate(
        action=action,
        mode=Mode.GENERAL,
        scope=Scope.PERSONAL,
    )

    return DecisionEvent.from_decision(
        decision,
        event_id=event_id,
        timestamp_ms=1000,
    )


def test_memory_store_append_creates_event_file(tmp_path):
    store = MemoryStore(tmp_path / "events.jsonl")
    event = make_event("test", "event-001")

    store.append(event)

    assert (tmp_path / "events.jsonl").exists()


def test_memory_store_preserves_event(tmp_path):
    store = MemoryStore(tmp_path / "events.jsonl")
    event = make_event("test", "event-002")

    store.append(event)

    events = store.read_all()

    assert len(events) == 1
    assert events[0] == event.to_dict()


def test_memory_store_is_append_only(tmp_path):
    store = MemoryStore(tmp_path / "events.jsonl")

    first = make_event("first", "event-001")
    second = make_event("second", "event-002")

    store.append(first)
    store.append(second)

    events = store.read_all()

    assert len(events) == 2
    assert events[0]["event_id"] == "event-001"
    assert events[1]["event_id"] == "event-002"


def test_memory_store_writes_valid_json_lines(tmp_path):
    store = MemoryStore(tmp_path / "events.jsonl")
    event = make_event("test", "event-003")

    store.append(event)

    lines = (tmp_path / "events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()

    assert len(lines) == 1
    assert json.loads(lines[0]) == event.to_dict()


def test_memory_store_empty_read(tmp_path):
    store = MemoryStore(tmp_path / "events.jsonl")

    assert store.read_all() == []
