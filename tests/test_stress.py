import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ahmad.core.events import DecisionEvent
from ahmad.core.types import Mode, Scope
from ahmad.governance.policy import PolicyEngine
from ahmad.memory.store import MemoryStore


def test_concurrent_decision_events(tmp_path: Path):
    """100 DecisionEvents في نفس الوقت"""
    store = MemoryStore(tmp_path / "concurrent.jsonl")
    
    def append_one(n):
        decision = PolicyEngine().evaluate(
            f"action-{n}", Mode.GENERAL, Scope.PERSONAL
        )
        event = DecisionEvent.from_decision(
            decision,
            event_id=f"event-{n}",
            request_id=f"request-{n}",
            timestamp_ms=1000 + n,
        )
        try:
            store.append(event)
            return "stored"
        except ValueError:
            return "rejected"
    
    with ThreadPoolExecutor(max_workers=10) as pool:
        outcomes = list(pool.map(append_one, range(100)))
    
    assert outcomes.count("stored") == 100
    assert outcomes.count("rejected") == 0
    events = store.read_all()
    assert len(events) == 100
    assert len({e["event_id"] for e in events}) == 100


def test_corrupted_jsonl_recovery(tmp_path: Path):
    """JSONL file مقطوع — يجب أن يقرأ الصالح ويتجاهل المكسور"""
    file_path = tmp_path / "corrupted.jsonl"
    
    valid_event = {
        "action": "test", "allowed": True, "event_id": "valid-1",
        "event_type": "decision", "mode": "general", "reason": "test",
        "scope": "personal", "timestamp_ms": 1000,
    }
    file_path.write_text(json.dumps(valid_event) + "\n")
    
    # سطر مكسور
    with file_path.open("a") as f:
        f.write('{"action": "broken", "event_id": "broken-1"')
        f.write("\n")
    
    # سطر صالح بعد المكسور
    valid_event_2 = {**valid_event, "event_id": "valid-2"}
    with file_path.open("a") as f:
        f.write(json.dumps(valid_event_2) + "\n")
    
    store = MemoryStore(file_path)
    events = store.read_all()
    
    # لازم يقرأ الصالح، يتجاهل المكسور
    assert len(events) == 2
    assert events[0]["event_id"] == "valid-1"
    assert events[1]["event_id"] == "valid-2"


def test_corrupted_jsonl_does_not_crash(tmp_path: Path, caplog):
    """خط مكسور واحد ما يوقف النظام"""
    file_path = tmp_path / "corrupted.jsonl"
    file_path.write_text('{"broken\n')
    
    store = MemoryStore(file_path)
    events = store.read_all()
    
    assert events == []
    assert any("corrupted" in r.message.lower() for r in caplog.records)
