from dataclasses import dataclass, field

import pytest

from ahmad.agents.coordinator import AgentSpec, MultiAgentCoordinator
from ahmad.providers.base import ProposedAction


@dataclass
class ProviderResponse:
    text: str
    proposed_actions: tuple = ()


@dataclass
class FakeProvider:
    name: str
    outputs: list[str]
    proposed_actions: tuple = ()
    requests: list = field(default_factory=list)

    def generate(self, request):
        self.requests.append(request)
        index = len(self.requests) - 1
        return ProviderResponse(
            self.outputs[index % len(self.outputs)],
            self.proposed_actions,
        )


class Registry:
    def __init__(self, *providers):
        self.providers = {provider.name: provider for provider in providers}

    def get(self, name):
        return self.providers.get(name)


def test_coordinator_obeys_round_and_turn_bounds_and_labels_turns():
    first = FakeProvider("p1", ["first"])
    second = FakeProvider("p2", ["second"])
    coordinator = MultiAgentCoordinator(
        Registry(first, second), max_rounds=5, max_turns=3
    )

    result = coordinator.run(
        "Discuss",
        [AgentSpec("a1", "planner", "p1"), AgentSpec("a2", "critic", "p2")],
        rounds=5,
    )

    assert len(result.turns) == 3
    assert len(first.requests) + len(second.requests) == 3
    assert "[a1 | planner]" in result.transcript
    assert "[a2 | critic]" in result.transcript


def test_coordinator_obeys_round_limit():
    provider = FakeProvider("p", ["response"])
    coordinator = MultiAgentCoordinator(Registry(provider), max_rounds=2)

    result = coordinator.run(
        "Discuss", [AgentSpec("agent", "helper", "p")], rounds=20
    )

    assert len(provider.requests) == 2
    assert len(result.turns) == 2


def test_proposed_actions_are_reported_as_ignored_and_never_executed():
    class Runtime:
        def __init__(self):
            self.providers = Registry(FakeProvider(
                "p", ["analysis"],
                (ProposedAction("delete-files"),),
            ))
            self.executed = []

        def handle(self, action):
            self.executed.append(action)

    runtime = Runtime()
    coordinator = MultiAgentCoordinator(runtime, max_rounds=2)

    result = coordinator.run("Review", [AgentSpec("reviewer", "reviewer", "p")])

    assert result.ignored_proposal_count == 2
    assert runtime.executed == []


def test_transcript_and_turn_output_are_bounded():
    provider = FakeProvider("p", ["x" * 500])
    coordinator = MultiAgentCoordinator(
        Registry(provider), max_rounds=4, max_turns=4,
        max_transcript_chars=180, max_turn_chars=40,
    )

    result = coordinator.run("question", [AgentSpec("agent", "helper", "p")])

    assert all(len(turn.content) <= 40 for turn in result.turns)
    assert len(result.transcript) <= 180
    assert len(provider.requests) == 4


def test_invalid_agent_roster_is_rejected():
    coordinator = MultiAgentCoordinator(Registry())

    with pytest.raises(ValueError, match="explicit IDs"):
        coordinator.run("prompt", [AgentSpec("", "helper", "missing")])
