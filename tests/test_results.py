import json

from ahmad.core.results import ResultEvent, ResultEventType
from ahmad.execution.mock_tool import ToolResult


def test_result_event_from_tool_result():
    result = ToolResult(
        success=True,
        tool="mock_tool",
        output="MOCK_EXECUTED:demo:mock",
    )

    event = ResultEvent.from_tool_result(
        result,
        event_id="result-001",
        decision_event_id="event-001",
        request_id="request-001",
        timestamp_ms=1234567890,
    )

    assert event.event_id == "result-001"
    assert event.timestamp_ms == 1234567890
    assert event.event_type is ResultEventType.RESULT
    assert event.decision_event_id == "event-001"
    assert event.success is True
    assert event.tool == "mock_tool"
    assert event.output == "MOCK_EXECUTED:demo:mock"


def test_result_event_from_denied_tool_result():
    result = ToolResult(
        success=False,
        tool="none",
        output="EXECUTION_DENIED",
    )

    event = ResultEvent.from_tool_result(
        result,
        event_id="result-002",
        decision_event_id="event-002",
        request_id="request-002",
        timestamp_ms=1000,
    )

    assert event.success is False
    assert event.tool == "none"
    assert event.output == "EXECUTION_DENIED"


def test_result_event_is_immutable():
    result = ToolResult(
        success=True,
        tool="mock_tool",
        output="test",
    )

    event = ResultEvent.from_tool_result(
        result,
        event_id="result-003",
        decision_event_id="event-003",
        request_id="request-003",
        timestamp_ms=1000,
    )

    try:
        event.success = False
    except AttributeError:
        pass
    else:
        raise AssertionError("ResultEvent must be immutable")


def test_result_event_json_is_deterministically_serialized():
    result = ToolResult(
        success=True,
        tool="mock_tool",
        output="test",
    )

    event = ResultEvent.from_tool_result(
        result,
        event_id="result-004",
        decision_event_id="event-004",
        request_id="request-004",
        timestamp_ms=2000,
    )

    expected = (
        '{"decision_event_id":"event-004","event_id":"result-004",'
        '"event_type":"result","output":"test","request_id":"request-004",'
        '"success":true,"timestamp_ms":2000,"tool":"mock_tool"}'
    )

    assert event.to_json() == expected
    assert json.loads(event.to_json()) == event.to_dict()
