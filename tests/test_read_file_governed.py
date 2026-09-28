"""Integration: ReadFileTool through ExecutionGateway (governed)."""
from pathlib import Path

from ahmad.core.events import DecisionEvent
from ahmad.core.types import Decision, Mode, Scope
from ahmad.execution.gateway import ExecutionGateway
from ahmad.execution.registry import Capability, ToolMetadata
from ahmad.memory.store import MemoryStore
from ahmad.tools.read_file import ReadFileTool


def _register_read_file(gateway: ExecutionGateway, root: Path) -> str:
    """Register ReadFileTool and return its binding_id."""
    tool = ReadFileTool(root=root)
    metadata = ToolMetadata(
        name="read_file",
        version="1.0",
        capabilities=("fs:read",),
        risk="low",
        implementation_id="read_file-v1",
    )
    gateway.registry.register("read_file", metadata, tool)
    return gateway.binding_id_for_action("read_file")


def _authorize_read_file(gateway: ExecutionGateway, binding_id: str):
    """Test-only policy: allow read_file with exact binding."""
    def test_policy(action, mode, scope, *, source=None, tool_binding_id=None):
        allowed = (
            action.startswith("read_file:")
            and scope is Scope.PERSONAL
            and tool_binding_id == binding_id
        )
        return Decision(
            action, mode, scope, allowed,
            "test-only read_file approval" if allowed else "default deny",
            source=source, tool_binding_id=tool_binding_id,
        )
    gateway.policy.evaluate = test_policy
    return test_policy


def test_read_file_through_gateway_success(tmp_path: Path):
    f = tmp_path / "note.txt"
    f.write_text("governed content")

    memory = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(memory=memory)
    binding_id = _register_read_file(gateway, tmp_path)
    _authorize_read_file(gateway, binding_id)

    action = f"read_file:{f}"
    decision = gateway.policy.evaluate(
        action, Mode.GENERAL, Scope.PERSONAL,
        tool_binding_id=binding_id,
    )
    event = DecisionEvent.from_decision(
        decision,
        event_id="read-file-1",
        request_id="req-read-1",
        timestamp_ms=1000,
    )
    memory.append(event)

    result = gateway.execute(
        decision,
        decision_event_id=event.event_id,
        result_event_id="read-file-1-result",
        request_id="req-read-1",
    )

    assert result.success is True
    assert result.tool == "read_file"
    assert result.output == "governed content"


def test_read_file_through_gateway_denied(tmp_path: Path):
    f = tmp_path / "secret.txt"
    f.write_text("should not be read")

    memory = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(memory=memory)
    binding_id = _register_read_file(gateway, tmp_path)
    # Do NOT authorize.

    action = f"read_file:{f}"
    decision = gateway.policy.evaluate(action, Mode.GENERAL, Scope.PERSONAL)
    event = DecisionEvent.from_decision(
        decision,
        event_id="read-file-denied",
        request_id="req-read-denied",
        timestamp_ms=1000,
    )
    memory.append(event)

    result = gateway.execute(
        decision,
        decision_event_id=event.event_id,
        result_event_id="read-file-denied-result",
        request_id="req-read-denied",
    )

    assert result.success is False
    assert result.output == "EXECUTION_DENIED"
    assert f.read_text() == "should not be read"  # unchanged


def test_read_file_missing_through_gateway(tmp_path: Path):
    memory = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(memory=memory)
    binding_id = _register_read_file(gateway, tmp_path)
    _authorize_read_file(gateway, binding_id)

    missing = tmp_path / "nope.txt"
    action = f"read_file:{missing}"
    decision = gateway.policy.evaluate(
        action, Mode.GENERAL, Scope.PERSONAL,
        tool_binding_id=binding_id,
    )
    event = DecisionEvent.from_decision(
        decision,
        event_id="read-file-missing",
        request_id="req-read-missing",
        timestamp_ms=1000,
    )
    memory.append(event)

    result = gateway.execute(
        decision,
        decision_event_id=event.event_id,
        result_event_id="read-file-missing-result",
        request_id="req-read-missing",
    )

    assert result.success is False
    assert "not found" in result.output
