import json
from pathlib import Path

import pytest

from ahmad.core.events import DecisionEvent
from ahmad.core.types import AgentRequest, Mode, Scope
from ahmad.core.runtime import AhmadRuntime
from ahmad.execution.gateway import ExecutionGateway
from ahmad.governance.policy import PolicyEngine
from ahmad.memory.store import MemoryStore
from ahmad.memory.local_memory import LocalMemoryStore
from ahmad.tools.local_memory import MemoryAddTool, MemoryForgetTool, MemorySearchTool


def test_local_memory_add_and_full_text_search(tmp_path: Path):
    store = LocalMemoryStore(tmp_path / "memories.sqlite3", owner_id="uid:1001")
    memory_id = store.add("The calibration fixture is stored in Lab 3.")

    matches = store.search("calibration Lab")

    assert len(matches) == 1
    assert matches[0]["id"] == memory_id
    assert matches[0]["content"] == "The calibration fixture is stored in Lab 3."


@pytest.mark.parametrize("journal_mode", ["DELETE", "WAL"])
def test_memory_is_partitioned_by_owner_and_forget_is_scoped(
    tmp_path: Path, journal_mode: str
):
    database = tmp_path / "memories.sqlite3"
    user_one = LocalMemoryStore(database, owner_id="uid:1001")
    user_two = LocalMemoryStore(database, owner_id="uid:1002")
    connection = user_one._connect()
    connection.execute(f"PRAGMA journal_mode={journal_mode}")
    connection.close()
    memory_id = user_one.add("private workshop detail")

    assert user_two.search("private") == []
    assert not user_two.forget(memory_id)
    assert user_one.search("private")[0]["id"] == memory_id
    assert user_one.forget(memory_id)
    assert user_one.search("private") == []
    for suffix in ("", "-wal", "-journal"):
        sqlite_file = Path(f"{database}{suffix}")
        if sqlite_file.exists():
            assert b"private workshop detail" not in sqlite_file.read_bytes()


def test_memory_is_persistent_and_unicode_searches(tmp_path: Path):
    database = tmp_path / "memories.sqlite3"
    LocalMemoryStore(database, owner_id="uid:42").add("مفتاح المختبر في الدرج")

    results = LocalMemoryStore(database, owner_id="uid:42").search("المختبر الدرج")

    assert len(results) == 1
    assert "مفتاح المختبر" in results[0]["content"]


@pytest.mark.parametrize(
    ("operation", "value"),
    [("add", ""), ("add", "x" * 10_001), ("search", ""), ("forget", 0)],
)
def test_local_memory_validates_input(tmp_path: Path, operation: str, value):
    store = LocalMemoryStore(tmp_path / "memories.sqlite3", owner_id="uid:42")

    with pytest.raises(ValueError):
        getattr(store, operation)(value)


def test_memory_tools_return_json_and_not_found(tmp_path: Path):
    store = LocalMemoryStore(tmp_path / "memories.sqlite3", owner_id="uid:42")
    add_result = MemoryAddTool(store).run(
        'memory_add:{"content":"remember the test fixture"}'
    )
    memory_id = json.loads(add_result.output)["id"]
    search_result = MemorySearchTool(store).run(
        'memory_search:{"query":"test fixture","limit":2}'
    )
    forget_result = MemoryForgetTool(store).run(
        f'memory_forget:{{"id":{memory_id}}}'
    )
    not_found_result = MemoryForgetTool(store).run(
        f'memory_forget:{{"id":{memory_id}}}'
    )

    assert add_result.success
    assert json.loads(search_result.output)[0]["id"] == memory_id
    assert forget_result.success
    assert not not_found_result.success
    assert "NOT_FOUND" in not_found_result.output


def test_memory_database_permissions_are_owner_only(tmp_path: Path):
    database = tmp_path / "memories.sqlite3"
    LocalMemoryStore(database, owner_id="uid:42")

    assert database.stat().st_mode & 0o777 == 0o600


def test_sensitive_memory_input_and_output_are_redacted_from_gateway_events(tmp_path: Path):
    event_store = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(memory=event_store)
    memory = LocalMemoryStore(tmp_path / "private.sqlite3", owner_id="uid:test")
    gateway.registry.replace_tool("memory_add", MemoryAddTool(memory))
    gateway.registry.replace_tool("memory_search", MemorySearchTool(memory))
    note = "private phrase for event-log redaction"

    for request_number, name, payload in (
        (1, "memory_add", {"content": note}),
        (2, "memory_search", {"query": "private phrase"}),
    ):
        action = f"{name}:{json.dumps(payload)}"
        binding = gateway.binding_id_for_action(action)
        decision = PolicyEngine().evaluate(
            name, Mode.GENERAL, Scope.PERSONAL, tool_binding_id=binding
        )
        event_id = f"decision-{request_number}"
        event_store.append(
            DecisionEvent.from_decision(
                decision,
                event_id=event_id,
                request_id=f"request-{request_number}",
                timestamp_ms=request_number,
            )
        )
        result = gateway.execute(
            decision,
            decision_event_id=event_id,
            result_event_id=f"{event_id}:result",
            request_id=f"request-{request_number}",
            execution_action=action,
        )
        assert result.success
        if name == "memory_search":
            assert note in result.output

    event_log = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert note not in event_log
    assert "private phrase" not in event_log
    assert "[sensitive output redacted]" in event_log


def test_runtime_uses_redacted_memory_action_and_request_id(tmp_path: Path):
    event_store = MemoryStore(tmp_path / "runtime-events.jsonl")
    runtime = AhmadRuntime(memory=event_store)
    runtime.gateway.registry.replace_tool(
        "memory_add",
        MemoryAddTool(LocalMemoryStore(tmp_path / "runtime-memory.sqlite3", owner_id="uid:test")),
    )
    private_note = "distinctive private runtime memory phrase"

    result = runtime.handle(
        AgentRequest(f'memory_add:{json.dumps({"content":private_note})}', Scope.PERSONAL)
    )

    assert result.success
    events = event_store.read_all()
    assert all(private_note not in json.dumps(event) for event in events)
    assert all("memory_add:" not in event.get("action", "") for event in events)
