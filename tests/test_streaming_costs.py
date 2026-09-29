import json
import shutil
import sys
import time
import uuid
from pathlib import Path

import pytest

from ahmad.core.runtime import AhmadRuntime
from ahmad.core.types import Mode
from ahmad.memory.store import MemoryStore
from ahmad.providers.base import ProviderAdapter, ProviderRequest, ProviderResult, ProposedAction
from ahmad.providers.hermes import HermesProvider
from ahmad.providers.registry import ProviderRegistry
from ahmad.providers.transports import SubprocessTransport, _RequestShim


@pytest.fixture
def test_dir():
    path = Path(".test-artifacts") / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def test_hermes_stream_yields_chunks_and_returns_final_result():
    transport = SubprocessTransport(
        [sys.executable, "-c", "import sys,time; print('first', flush=True); time.sleep(.1); print('second', flush=True)"],
        timeout=3,
    )
    provider = HermesProvider(transport=transport)
    iterator = provider.generate_stream(ProviderRequest("stream-1", "hello", Mode.GENERAL))

    first = next(iterator)
    assert "first" in first
    second = next(iterator)
    assert "second" in second
    with pytest.raises(StopIteration) as stopped:
        next(iterator)
    assert isinstance(stopped.value.value, ProviderResult)
    assert stopped.value.value.text == first + second


def test_subprocess_stream_reports_nonzero_exit_and_timeout():
    failing = SubprocessTransport(
        [sys.executable, "-c", "import sys; print('broken', file=sys.stderr); sys.exit(7)"],
        timeout=2,
    )
    with pytest.raises(RuntimeError, match="exit 7.*broken"):
        list(failing.stream(_RequestShim("prompt")))

    slow = SubprocessTransport(
        [sys.executable, "-c", "import time; time.sleep(2)"],
        timeout=0.1,
    )
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="timed out"):
        list(slow.stream(_RequestShim("prompt")))
    assert time.monotonic() - started < 1.5


def test_runtime_stream_persists_turn_and_governs_final_proposals(test_dir):
    providers = ProviderRegistry()

    class StreamingProvider(ProviderAdapter):
        def generate_stream(self, request):
            yield "part one "
            yield "part two"
            return ProviderResult(
                self.name,
                True,
                text="part one part two",
                proposed_actions=(ProposedAction("shell:execute"),),
                metadata={"usage": {"input_tokens": 10, "output_tokens": 4}},
            )

    providers.register(StreamingProvider(name="streamer"))
    runtime = AhmadRuntime(
        memory=MemoryStore(test_dir / "events.jsonl"),
        providers=providers,
        cost_ledger_path=test_dir / "costs.jsonl",
        conversations_dir=test_dir / "conversations",
    )
    chunks = runtime.stream_provider_request(
        "streamer", "private prompt", request_id="stream-call", conversation_id="stream"
    )

    assert next(chunks) == "part one "
    assert runtime._get_conversation("stream").render_prompt("next").startswith(
        "User: private prompt\nUser: next"
    )
    assert next(chunks) == "part two"
    with pytest.raises(StopIteration):
        next(chunks)

    outcome = runtime.last_stream_outcome
    assert outcome.response.text == "part one part two"
    assert len(outcome.tool_results) == 1
    assert outcome.tool_results[0].success is False
    assert runtime._get_conversation("stream").render_prompt("next").startswith(
        "User: private prompt\nAssistant: part one part two"
    )
    record = json.loads((test_dir / "costs.jsonl").read_text().strip())
    assert record["request_id"] == "stream-call"
    assert record["input_tokens"] == 10
    assert record["output_tokens"] == 4
    assert record["cost_basis"] == "unknown"
    assert "private prompt" not in (test_dir / "costs.jsonl").read_text()


def test_cost_ledger_uses_configured_rates_as_explicit_estimate(test_dir):
    providers = ProviderRegistry()
    providers.register(ProviderAdapter(lambda req: "abcdefgh", name="metered"))
    runtime = AhmadRuntime(
        memory=MemoryStore(test_dir / "events.jsonl"),
        providers=providers,
        cost_ledger_path=test_dir / "costs.jsonl",
        conversations_dir=test_dir / "conversations",
        provider_rates={
            "metered": {"input_per_million": 2.0, "output_per_million": 4.0}
        },
    )
    runtime.handle_provider_request(
        "metered", "12345678", request_id="estimated-call",
        conversation_id="estimated",
    )
    record = json.loads((test_dir / "costs.jsonl").read_text().strip())

    assert record["input_tokens"] == 2
    assert record["output_tokens"] == 2
    assert record["usage_basis"] == "estimated_characters"
    assert record["cost"] == pytest.approx(0.000012)
    assert record["cost_basis"] == "estimated_configured_rates"
    assert (test_dir / "costs.jsonl").stat().st_mode & 0o777 == 0o600


def test_cost_ledger_preserves_provider_reported_cost(test_dir):
    providers = ProviderRegistry()
    providers.register(ProviderAdapter(
        lambda req: ProviderResult(
            "cost-source", True, text="done",
            metadata={
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
                "cost_usd": 0.0042,
            },
        ),
        name="cost-source",
    ))
    runtime = AhmadRuntime(
        memory=MemoryStore(test_dir / "events.jsonl"),
        providers=providers,
        cost_ledger_path=test_dir / "costs.jsonl",
        conversations_dir=test_dir / "conversations",
    )

    runtime.handle_provider_request(
        "cost-source", "prompt", request_id="reported-call", conversation_id="reported"
    )
    record = json.loads((test_dir / "costs.jsonl").read_text().strip())

    assert record["input_tokens"] == 12
    assert record["output_tokens"] == 3
    assert record["cost"] == 0.0042
    assert record["cost_basis"] == "provider_reported"
