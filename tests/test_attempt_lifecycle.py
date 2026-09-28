from pathlib import Path
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor

import pytest

from ahmad.core.events import DecisionEvent
from ahmad.core.resolutions import ResolutionEvent
from ahmad.core.runtime import AhmadRuntime
from ahmad.core.types import AgentRequest, EffectStatus, Mode, ResolutionPath, ResolutionResult, Scope
from ahmad.execution.gateway import ExecutionGateway
from ahmad.execution.mock_tool import ToolResult
from ahmad.governance.policy import PolicyEngine
from ahmad.memory.attempt_projection import AttemptProjection
from ahmad.memory.sqlite_store import SQLiteEventStore
from ahmad.memory.store import MemoryStore, _resolution_writer_for
from ahmad.execution.registry import IdempotencyGuarantee, ReconcileContract


def allow_current_binding(gateway):
    binding_id = gateway.binding_id_for_action("demo:mock")
    gateway.policy.evaluate = lambda action, mode, scope, *, source=None, tool_binding_id=None: __import__(
        "ahmad.core.types", fromlist=["Decision"]
    ).Decision(action, mode, scope, tool_binding_id == binding_id,
               "test approval", source=source, tool_binding_id=tool_binding_id)
    return binding_id


def test_attempt_is_persisted_before_tool_and_result_after(tmp_path):
    store = MemoryStore(tmp_path / "events.jsonl")
    runtime = AhmadRuntime(memory=store)
    observations = []

    class Observe:
        def run(self, action):
            observations.append([event["event_type"] for event in store.read_all()])
            return ToolResult(True, "observe", "ok")

    runtime.gateway.registry.replace_tool("demo:mock", Observe())
    allow_current_binding(runtime.gateway)
    runtime.handle(AgentRequest("demo:mock", request_id="attempt-order"), event_id="decision-order")
    assert observations == [["decision", "attempt_created", "attempt_started"]]
    assert [e["event_type"] for e in store.read_all()] == [
        "decision", "attempt_created", "attempt_started", "result"
    ]
    result = store.read_all()[-1]
    assert result["attempt_id"] == store.read_all()[1]["attempt_id"]
    assert result["request_id"] == "attempt-order"


def test_tool_exception_records_failure_and_ambiguity(tmp_path):
    store = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(store, PolicyEngine())
    binding_id = allow_current_binding(gateway)

    class Explodes:
        def run(self, action):
            raise RuntimeError("failure")

    gateway.registry.replace_tool("demo:mock", Explodes())
    binding_id = gateway.binding_id_for_action("demo:mock")
    gateway.policy.evaluate = lambda action, mode, scope, *, source=None, tool_binding_id=None: __import__(
        "ahmad.core.types", fromlist=["Decision"]
    ).Decision(action, mode, scope, True, "test approval", source=source,
               tool_binding_id=tool_binding_id)
    decision = gateway.policy.evaluate("demo:mock", Mode.GENERAL, Scope.PERSONAL,
                                       tool_binding_id=binding_id)
    store.append(DecisionEvent.from_decision(decision, event_id="d-explode", request_id="r-explode"))
    with pytest.raises(RuntimeError):
        gateway.execute(decision, decision_event_id="d-explode", result_event_id="r-explode-result",
                        request_id="r-explode")
    events = store.read_all()
    failed = next(e for e in events if e["event_type"] == "result")
    assert failed["success"] is False and failed["effect_status"] == "unknown"
    assert events[-1]["event_type"] == "attempt_ambiguous"


def test_tool_cannot_self_declare_failed_clean_without_registry_guarantee(tmp_path):
    store = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(store)

    class ClaimsNoEffect:
        def run(self, action):
            return ToolResult(False, "untrusted", "failed", EffectStatus.NOT_APPLIED)

    gateway.registry.replace_tool("demo:mock", ClaimsNoEffect())
    binding = allow_current_binding(gateway)
    decision = gateway.policy.evaluate("demo:mock", Mode.GENERAL, Scope.PERSONAL,
                                       tool_binding_id=binding)
    store.append(DecisionEvent.from_decision(decision, event_id="d-untrusted-effect", request_id="r"))
    result = gateway.execute(decision, decision_event_id="d-untrusted-effect",
                             result_event_id="r-untrusted-effect", request_id="r")
    assert result.effect_status is EffectStatus.UNKNOWN
    assert store.read_all()[-1]["event_type"] == "attempt_ambiguous"


def test_result_storage_failure_preserves_orphan_in_flight_as_ambiguous(tmp_path):
    state = {"effects": 0}

    class Tool:
        def run(self, action):
            state["effects"] += 1
            return ToolResult(True, "external", "applied")

    class Store(MemoryStore):
        def append(self, event):
            if getattr(event, "event_type", None).value == "result":
                raise OSError("storage failed")
            super().append(event)

    store = Store(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(store)
    gateway.registry.replace_tool("demo:mock", Tool())
    binding_id = allow_current_binding(gateway)
    decision = gateway.policy.evaluate("demo:mock", Mode.GENERAL, Scope.PERSONAL,
                                       tool_binding_id=binding_id)
    store.append(DecisionEvent.from_decision(decision, event_id="d-fail", request_id="r-fail"))
    with pytest.raises(OSError):
        gateway.execute(decision, decision_event_id="d-fail", result_event_id="r-fail-result",
                        request_id="r-fail")
    assert state["effects"] == 1
    events = store.read_all()
    assert events[-1]["event_type"] == "attempt_ambiguous"
    assert "no rollback" not in events[-1]["reason"].lower()


def test_recovery_marks_orphaned_in_flight_ambiguous(tmp_path):
    store = MemoryStore(tmp_path / "events.jsonl")
    runtime = AhmadRuntime(memory=store)
    allow_current_binding(runtime.gateway)
    # Establish the durable pre-dispatch records without completing a tool call.
    from ahmad.core.attempts import AttemptCreatedEvent, AttemptStartedEvent
    store.append(DecisionEvent.from_decision(
        runtime.policy.evaluate("x", Mode.GENERAL, Scope.PERSONAL),
        event_id="d-recover", request_id="r-recover"))
    store.append(AttemptCreatedEvent(
        "a:created", 1, "a", "r-recover", "x", "general", "personal", "binding",
        "key", "scope", "digest", "canon-v1", decision_event_id="d-recover"))
    store.append(AttemptStartedEvent("a:started", 2, "a", "r-recover", "d-recover", "binding", "lease"))
    projection = AttemptProjection(store.read_all())
    assert projection.recover_in_flight(store, now_ms=99) == 1
    assert AttemptProjection(store.read_all()).attempts()["a"]["state"] == "ambiguous"


def test_runtime_startup_recovery_is_explicit_and_marks_unknown(tmp_path):
    store = MemoryStore(tmp_path / "events.jsonl")
    store.append(DecisionEvent.from_decision(
        PolicyEngine().evaluate("action", Mode.GENERAL, Scope.PERSONAL),
        event_id="startup-decision", request_id="startup-request"))
    from ahmad.core.attempts import AttemptCreatedEvent, AttemptStartedEvent
    store.append(AttemptCreatedEvent(
        "startup-attempt:created", 1, "startup-attempt", "startup-request", "action",
        "general", "personal", "binding", "key", "scope", "digest", "json-c14n-v1",
        decision_event_id="startup-decision"))
    store.append(AttemptStartedEvent(
        "startup-attempt:started", 2, "startup-attempt", "startup-request",
        "startup-decision", "binding", "lease"))
    AhmadRuntime(memory=store, recover_in_flight_on_startup=True)
    recovered = AttemptProjection(store.read_all()).attempts()["startup-attempt"]
    assert recovered["state"] == "ambiguous"
    assert recovered["request_id"] == "startup-request"
    assert recovered["decision_event_id"] == "startup-decision"


def test_persisted_pending_attempt_can_resume_before_dispatch(tmp_path):
    class StartFailsOnce(MemoryStore):
        fail = True
        def append(self, event):
            if getattr(event, "event_type", None).value == "attempt_started" and self.fail:
                self.fail = False
                raise OSError("start record unavailable")
            super().append(event)

    calls = []
    class Tool:
        def run(self, action):
            calls.append(action)
            return ToolResult(True, "tool", "ok")

    store = StartFailsOnce(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(store)
    gateway.registry.replace_tool("demo:mock", Tool())
    binding = allow_current_binding(gateway)
    decision = gateway.policy.evaluate("demo:mock", Mode.GENERAL, Scope.PERSONAL,
                                       tool_binding_id=binding)
    store.append(DecisionEvent.from_decision(decision, event_id="d-pending", request_id="r-pending"))
    with pytest.raises(OSError, match="start record"):
        gateway.execute(decision, decision_event_id="d-pending", result_event_id="res-pending",
                        request_id="r-pending")
    assert calls == []
    result = gateway.execute(decision, decision_event_id="d-pending", result_event_id="res-pending",
                             request_id="r-pending")
    assert result.success and calls == ["demo:mock"]
    assert len([e for e in store.read_all() if e.get("event_type") == "attempt_created"]) == 1


def test_resolution_requires_evidence_and_manual_identity():
    with pytest.raises(ValueError, match="evidence_ref"):
        ResolutionEvent("e", 1, "resolution", "a", "amb", "r", "d", "binding", "key", "digest",
                        ResolutionResult.CLEARED_FOR_RETRY, ResolutionPath.IDEMPOTENT_RETRY, "",
                        guarantee_id="g", guarantee_version="1")
    with pytest.raises(ValueError, match="manual identity"):
        ResolutionEvent("e", 1, "resolution", "a", "amb", "r", "d", "binding", "key", "digest",
                        ResolutionResult.CLEARED_FOR_RETRY, ResolutionPath.MANUAL_RECONCILIATION,
                        "evidence")


def test_attempt_event_cannot_start_in_another_lifecycle_state():
    from ahmad.core.attempts import AttemptCreatedEvent
    from ahmad.core.types import AttemptState
    with pytest.raises(ValueError, match="must start in PENDING"):
        AttemptCreatedEvent("e", 1, "a", "r", "x", "general", "personal", "b",
                            "key", "scope", "digest", "canon-v1", state=AttemptState.AMBIGUOUS)


def test_manual_reconciliation_denies_without_trusted_gateway_authorizer(tmp_path):
    gateway = ExecutionGateway(MemoryStore(tmp_path / "events.jsonl"))
    with pytest.raises(PermissionError, match="disabled by default"):
        gateway.reconcile_manually({}, resolution_event_id="r", evidence_ref="x",
                                   evidence="x", result=ResolutionResult.CLEARED_FOR_RETRY)


@pytest.mark.parametrize("mismatch", ["matching", "scope", "binding"])
def test_manual_reconciliation_authorization_is_scoped_to_attempt_and_binding(tmp_path, mismatch):
    store = MemoryStore(tmp_path / f"manual-{mismatch}.jsonl")

    class Authorizer:
        def __init__(self):
            self.decision_id = "manual-authorization"

        def authorize(self, attempt):
            return "reviewed-operator", self.decision_id

    authorizer = Authorizer()
    gateway = ExecutionGateway(store, manual_authorizer=authorizer)

    class UnknownTool:
        def run(self, action):
            raise TimeoutError("unknown effect")

    gateway.registry.replace_tool("demo:mock", UnknownTool())
    binding_id = allow_current_binding(gateway)
    decision = gateway.policy.evaluate("demo:mock", Mode.GENERAL, Scope.PERSONAL,
                                       tool_binding_id=binding_id)
    store.append(DecisionEvent.from_decision(decision, event_id="manual-original",
                                             request_id="manual-request"))
    with pytest.raises(TimeoutError):
        gateway.execute(decision, decision_event_id="manual-original",
                        result_event_id="manual-result", request_id="manual-request")
    attempt = AttemptProjection(store.read_all()).attempts()["attempt:manual-original"]

    from ahmad.core.types import Decision
    authorization = Decision(
        action="manual:reconcile", mode=Mode.GENERAL,
        scope=Scope.AUTHORIZED if mismatch == "scope" else Scope.PERSONAL,
        allowed=True, reason="explicit manual authorization",
        tool_binding_id="different-binding" if mismatch == "binding" else binding_id,
    )
    store.append(DecisionEvent.from_decision(
        authorization, event_id=authorizer.decision_id, request_id="manual-request"))

    if mismatch == "matching":
        resolution = gateway.reconcile_manually(
            attempt, resolution_event_id="manual-resolution", evidence_ref="reviewed-evidence",
            evidence="observed manually", result=ResolutionResult.CONFIRMED_TERMINAL,
            terminal_finding="applied",
        )
        assert resolution.resolution_result is ResolutionResult.CONFIRMED_TERMINAL
        assert any(event.get("event_type") == "resolution" for event in store.read_all())
    else:
        with pytest.raises(PermissionError, match="matching PolicyEngine DecisionEvent"):
            gateway.reconcile_manually(
                attempt, resolution_event_id="manual-resolution", evidence_ref="reviewed-evidence",
                evidence="observed manually", result=ResolutionResult.CONFIRMED_TERMINAL,
                terminal_finding="applied",
            )
        assert not any(event.get("event_type") == "resolution" for event in store.read_all())


@pytest.mark.parametrize("store_kind", ["jsonl", "sqlite"])
def test_direct_resolution_event_write_is_rejected(tmp_path, store_kind):
    store = (MemoryStore(tmp_path / "events.jsonl") if store_kind == "jsonl"
             else SQLiteEventStore(tmp_path / "events.db"))
    event = ResolutionEvent(
        "unauthorized-resolution", 1, "unauthorized-resolution", "attempt", "ambiguous",
        "request", "decision", "binding", "key", "digest",
        ResolutionResult.CLEARED_FOR_RETRY, ResolutionPath.IDEMPOTENT_RETRY, "contract",
        guarantee_id="g", guarantee_version="v1")
    with pytest.raises(PermissionError, match="Gateway resolution writer"):
        store.append(event)


def test_sqlite_enforces_claim_uniqueness_across_reopen(tmp_path):
    store = SQLiteEventStore(tmp_path / "events.db")
    event = DecisionEvent.from_decision(
        PolicyEngine().evaluate("x", Mode.GENERAL, Scope.PERSONAL),
        event_id="claim-one", request_id="r")
    store.append_with_claims(event, (("attempt_id", "attempt-1", "attempt-1"),))
    reopened = SQLiteEventStore(tmp_path / "events.db")
    assert reopened.claim("attempt_id", "attempt-1") == "attempt-1"
    duplicate = DecisionEvent.from_decision(
        PolicyEngine().evaluate("x", Mode.GENERAL, Scope.PERSONAL),
        event_id="claim-two", request_id="r2")
    with pytest.raises(Exception):
        reopened.append_with_claims(duplicate, (("attempt_id", "attempt-1", "different"),))
    assert reopened.read("claim-two") is None


def test_sqlite_attempt_claim_is_atomic_under_concurrent_appends(tmp_path):
    store = SQLiteEventStore(tmp_path / "concurrent.db")
    from ahmad.core.attempts import AttemptCreatedEvent
    events = [AttemptCreatedEvent(
        f"attempt-event-{n}", 1, "same-attempt", "request", "action", "general", "personal",
        "binding", "key", "scope", "digest", "json-c14n-v1") for n in range(2)]

    def append(event):
        try:
            store.append(event)
            return "stored"
        except Exception:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(append, events))
    assert outcomes.count("stored") == 1
    assert len([event for event in store.read_all() if event.get("event_type") == "attempt_created"]) == 1


def test_authoritative_reconcile_retry_uses_new_decision_and_attempt(tmp_path):
    store = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(store)
    calls = []

    class ReconciledTool:
        def run(self, action):
            calls.append("execute")
            if len(calls) == 1:
                raise TimeoutError("unknown remote outcome")
            return ToolResult(True, "reconciled", "ok")

        def reconcile(self, idempotency_key):
            calls.append(f"reconcile:{idempotency_key}")
            return "not_applied"

    old = gateway.registry._resolve_binding("demo:mock")
    metadata = replace(old.metadata, reconcile_contract=ReconcileContract(
        "mock-reconciler", "v1", True, True, "test-contract"))
    gateway.registry.replace_tool("demo:mock", ReconciledTool(), metadata=metadata)
    binding = gateway.registry._resolve_binding("demo:mock")
    allow_current_binding(gateway)
    decision = gateway.policy.evaluate("demo:mock", Mode.GENERAL, Scope.PERSONAL,
                                       tool_binding_id=binding.binding_id)
    store.append(DecisionEvent.from_decision(decision, event_id="initial-decision",
                                             request_id="logical-request"))
    with pytest.raises(TimeoutError):
        gateway.execute(decision, decision_event_id="initial-decision",
                        result_event_id="initial-result", request_id="logical-request")
    attempt = AttemptProjection(store.read_all()).attempts()["attempt:initial-decision"]
    resolution = gateway.reconcile_ambiguous(
        attempt, resolution_event_id="resolution-retry", now_ms=100,
    )
    assert resolution.resolution_result is ResolutionResult.CLEARED_FOR_RETRY
    child = next(e for e in store.read_all() if e.get("resolved_from_resolution_event_id") == "resolution-retry")
    retry_decision = gateway.policy.evaluate("demo:mock", Mode.GENERAL, Scope.PERSONAL,
                                             tool_binding_id=binding.binding_id)
    store.append(DecisionEvent.from_decision(retry_decision, event_id="retry-decision",
                                             request_id="logical-request"))
    result = gateway.execute(retry_decision, decision_event_id="retry-decision",
                             result_event_id="retry-result", request_id="logical-request",
                             attempt_id=child["attempt_id"])
    assert result.success
    assert calls[0] == "execute" and calls[1].startswith("reconcile:") and calls[2] == "execute"
    events = store.read_all()
    assert child["attempt_id"] != attempt["attempt_id"]
    assert events[-1]["attempt_id"] == child["attempt_id"]
    assert events[-1]["decision_event_id"] == "retry-decision"


def test_idempotency_retry_reuses_key_but_requires_new_attempt_and_decision(tmp_path):
    store = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(store)
    keys = []

    class IdempotentTool:
        def run(self, action, *, idempotency_key):
            keys.append(idempotency_key)
            if len(keys) == 1:
                return ToolResult(False, "idempotent", "unknown", EffectStatus.UNKNOWN)
            return ToolResult(True, "idempotent", "ok", EffectStatus.APPLIED)

    old = gateway.registry._resolve_binding("demo:mock")
    guarantee = IdempotencyGuarantee(
        "test-dedup", "v1", "action-binding", "canonical-json-sha256",
        "exact-binding", "tool-enforced-key", 60000, "reviewed-test-contract")
    gateway.registry.replace_tool("demo:mock", IdempotentTool(),
                                  metadata=replace(old.metadata, idempotency_guarantee=guarantee))
    binding = gateway.registry._resolve_binding("demo:mock")
    allow_current_binding(gateway)
    decision = gateway.policy.evaluate("demo:mock", Mode.GENERAL, Scope.PERSONAL,
                                       tool_binding_id=binding.binding_id)
    store.append(DecisionEvent.from_decision(decision, event_id="idem-first",
                                             request_id="idem-request"))
    first = gateway.execute(decision, decision_event_id="idem-first", result_event_id="idem-result",
                            request_id="idem-request")
    assert not first.success
    attempt = AttemptProjection(store.read_all()).attempts()["attempt:idem-first"]
    resolution = gateway.clear_ambiguous_for_idempotent_retry(
        binding, attempt, resolution_event_id="idem-resolution")
    assert resolution.resolution_result is ResolutionResult.CLEARED_FOR_RETRY
    child = next(e for e in store.read_all() if e.get("resolved_from_resolution_event_id") == "idem-resolution")
    second_decision = gateway.policy.evaluate("demo:mock", Mode.GENERAL, Scope.PERSONAL,
                                              tool_binding_id=binding.binding_id)
    store.append(DecisionEvent.from_decision(second_decision, event_id="idem-second",
                                             request_id="idem-request"))
    result = gateway.execute(second_decision, decision_event_id="idem-second",
                             result_event_id="idem-second-result", request_id="idem-request",
                             attempt_id=child["attempt_id"])
    assert result.success
    assert keys[0] == keys[1] == attempt["idempotency_key"]
    assert child["attempt_id"] != attempt["attempt_id"]


def test_attention_required_is_derived_and_never_written(tmp_path):
    store = MemoryStore(tmp_path / "events.jsonl")
    resolution = ResolutionEvent(
        "res-id", 100, "res-id", "attempt-1", "amb-event", "request-1", "decision-1",
        "binding", "key", "digest", ResolutionResult.CLEARED_FOR_RETRY,
        ResolutionPath.IDEMPOTENT_RETRY, "contract", guarantee_id="g", guarantee_version="v1")
    _resolution_writer_for(store).append(resolution)
    projection = AttemptProjection(store.read_all())
    items = projection.attention_required(now_ms=200, linkage_sla_ms=50)
    assert items and items[0].kind == "missing_retry_child"
    assert store.read("res-id")["resolution_result"] == "cleared_for_retry"
    assert all(item.get("event_type") != "attention_required" for item in store.read_all())


@pytest.mark.parametrize(
    ("contract_authoritative", "outcome", "expected"),
    [(True, "applied", "confirmed_terminal"), (False, "applied", None),
     (True, "unknown", None), (True, "error", None)],
)
def test_reconciliation_authority_and_closed_outcomes(tmp_path, contract_authoritative, outcome, expected):
    store = MemoryStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(store)

    class Reconciler:
        def run(self, action):
            raise TimeoutError()
        def reconcile(self, idempotency_key):
            return outcome

    old = gateway.registry._resolve_binding("demo:mock")
    metadata = replace(old.metadata, reconcile_contract=ReconcileContract(
        "reconciler", "v1", True, contract_authoritative, "reviewed-contract"))
    gateway.registry.replace_tool("demo:mock", Reconciler(), metadata=metadata)
    binding_id = allow_current_binding(gateway)
    decision = gateway.policy.evaluate("demo:mock", Mode.GENERAL, Scope.PERSONAL,
                                       tool_binding_id=binding_id)
    store.append(DecisionEvent.from_decision(decision, event_id="reconcile-decision", request_id="rr"))
    with pytest.raises(TimeoutError):
        gateway.execute(decision, decision_event_id="reconcile-decision",
                        result_event_id="reconcile-result", request_id="rr")
    attempt = AttemptProjection(store.read_all()).attempts()["attempt:reconcile-decision"]
    result = gateway.reconcile_ambiguous(attempt, resolution_event_id="resolution-outcome", now_ms=123)
    if expected is None:
        assert result is None
        assert not any(e.get("event_type") == "resolution" for e in store.read_all())
    else:
        assert result.resolution_result.value == expected
        assert not any(e.get("resolved_from_resolution_event_id") for e in store.read_all())


def test_resolution_append_failure_leaves_evidence_but_no_retry_child(tmp_path):
    class ResolutionStore(MemoryStore):
        fail_resolution = False
        def _append_resolution(self, event, *, authority):
            if getattr(event, "event_type", None).value == "resolution" and self.fail_resolution:
                raise OSError("resolution append failed")
            super()._append_resolution(event, authority=authority)

    store = ResolutionStore(tmp_path / "events.jsonl")
    gateway = ExecutionGateway(store)
    class Reconciler:
        def run(self, action):
            raise TimeoutError()
        def reconcile(self, idempotency_key):
            return "not_applied"
    old = gateway.registry._resolve_binding("demo:mock")
    gateway.registry.replace_tool("demo:mock", Reconciler(), metadata=replace(
        old.metadata, reconcile_contract=ReconcileContract("reconciler", "v1", True, True, "contract")))
    binding_id = allow_current_binding(gateway)
    decision = gateway.policy.evaluate("demo:mock", Mode.GENERAL, Scope.PERSONAL,
                                       tool_binding_id=binding_id)
    store.append(DecisionEvent.from_decision(decision, event_id="d-res-fail", request_id="r-res-fail"))
    with pytest.raises(TimeoutError):
        gateway.execute(decision, decision_event_id="d-res-fail", result_event_id="result-res-fail",
                        request_id="r-res-fail")
    attempt = AttemptProjection(store.read_all()).attempts()["attempt:d-res-fail"]
    store.fail_resolution = True
    with pytest.raises(OSError, match="resolution append"):
        gateway.reconcile_ambiguous(attempt, resolution_event_id="res-fail", now_ms=500)
    events = store.read_all()
    assert any(e.get("event_type") == "reconcile_evidence" for e in events)
    assert not any(e.get("event_type") == "resolution" for e in events)
    assert not any(e.get("resolved_from_resolution_event_id") for e in events)
