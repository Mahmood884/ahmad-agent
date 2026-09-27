from ahmad.memory.projections import (
    DecisionProjection,
    RuntimeStateProjection,
    ToolUsageProjection,
)


def test_projections_rebuild_from_event_records():
    events = [
        {"event_type": "decision", "event_id": "d1", "request_id": "r1", "allowed": True},
        {"event_type": "result", "event_id": "x1", "request_id": "r1", "tool": "mock", "success": True},
    ]
    decisions = DecisionProjection()
    runtime = RuntimeStateProjection()
    usage = ToolUsageProjection()

    for projection in (decisions, runtime, usage):
        projection.rebuild(events)
        snapshot = repr(projection)
        projection.rebuild([])
        assert repr(projection) != snapshot
        projection.rebuild(events)

    assert decisions.decisions["d1"]["allowed"] is True
    assert runtime.latest_by_request["r1"]["event_type"] == "result"
    assert usage.counts[("mock", True)] == 1
