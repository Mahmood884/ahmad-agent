from ahmad.core.runtime import AhmadRuntime
from ahmad.core.types import AgentRequest
from ahmad.memory.store import MemoryStore


def test_runtime_correlates_decision_and_result_with_deterministic_request_id(tmp_path):
    runtime = AhmadRuntime(memory=MemoryStore(tmp_path / "events.jsonl"))

    runtime.handle(AgentRequest("hello Ahmad"))

    decision, result = runtime.memory.read_all()
    assert decision["request_id"].startswith("req-")
    assert result["request_id"] == decision["request_id"]
    assert result["decision_event_id"] == decision["event_id"]


def test_request_id_can_be_supplied_by_caller(tmp_path):
    runtime = AhmadRuntime(memory=MemoryStore(tmp_path / "events.jsonl"))

    runtime.handle(AgentRequest("hello Ahmad", request_id="request-from-caller"))

    decision, result = runtime.memory.read_all()
    assert decision["request_id"] == "request-from-caller"
    assert result["request_id"] == "request-from-caller"
