"""Bounded provider coordination without tool execution or governance authority."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
from typing import Any, Iterable
from uuid import uuid4

from ahmad.core.types import Mode
from ahmad.providers.base import ProviderRequest


@dataclass(frozen=True)
class AgentSpec:
    agent_id: str
    role: str
    provider_name: str


@dataclass(frozen=True)
class AgentTurn:
    agent_id: str
    role: str
    content: str


@dataclass(frozen=True)
class CoordinationResult:
    turns: tuple[AgentTurn, ...]
    ignored_proposal_count: int

    @property
    def transcript(self) -> str:
        return "\n".join(
            f"[{turn.agent_id} | {turn.role}]\n{turn.content}"
            for turn in self.turns
        )


class MultiAgentCoordinator:
    """Ask registered providers to collaborate within strict local bounds.

    The coordinator reads provider output only. Proposed actions are deliberately
    discarded; execution remains exclusively in the existing governed runtime.
    """

    def __init__(
        self,
        runtime_or_registry: Any,
        *,
        max_rounds: int = 3,
        max_turns: int = 12,
        max_transcript_chars: int = 12_000,
        max_turn_chars: int = 2_000,
    ) -> None:
        bounds = (max_rounds, max_turns, max_transcript_chars, max_turn_chars)
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 1
               for value in bounds):
            raise ValueError("coordinator bounds must be positive")
        self._registry = getattr(runtime_or_registry, "providers", runtime_or_registry)
        self._router = getattr(runtime_or_registry, "router", None)
        self.max_rounds = max_rounds
        self.max_turns = max_turns
        self.max_transcript_chars = max_transcript_chars
        self.max_turn_chars = max_turn_chars

    def run(
        self,
        prompt: str,
        agents: Iterable[AgentSpec],
        *,
        rounds: int | None = None,
    ) -> CoordinationResult:
        """Coordinate a fixed roster; each agent speaks at most once per round."""
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be non-empty text")
        user_prefix = f"[user]\n{prompt}"
        if len(user_prefix) > self.max_transcript_chars:
            raise ValueError("prompt exceeds the transcript size limit")
        roster = tuple(islice(iter(agents), self.max_turns + 1))
        if len(roster) > self.max_turns:
            raise ValueError("agent roster exceeds the maximum turn count")
        if not roster or any(
            not isinstance(agent, AgentSpec)
            or not isinstance(agent.agent_id, str)
            or not isinstance(agent.role, str)
            or not isinstance(agent.provider_name, str)
            or not agent.agent_id.strip()
            or not agent.role.strip()
            or not agent.provider_name.strip()
            or len(agent.agent_id) > 128
            or len(agent.role) > 128
            or len(agent.provider_name) > 128
            for agent in roster
        ):
            raise ValueError("agents must have explicit IDs, roles, and provider names")
        if len({agent.agent_id for agent in roster}) != len(roster):
            raise ValueError("agent IDs must be unique")
        if rounds is not None and (
            not isinstance(rounds, int) or isinstance(rounds, bool)
        ):
            raise ValueError("rounds must be a positive integer")
        round_limit = self.max_rounds if rounds is None else min(rounds, self.max_rounds)
        if round_limit < 1:
            raise ValueError("rounds must be positive")

        turns: list[AgentTurn] = []
        turn_count = 0
        ignored_proposals = 0
        for _ in range(round_limit):
            for agent in roster:
                if turn_count >= self.max_turns:
                    return CoordinationResult(tuple(turns), ignored_proposals)
                header = f"[{agent.agent_id} | {agent.role}]\n"
                available = (
                    self.max_transcript_chars - len(user_prefix) - 2 - len(header)
                )
                if available < 0:
                    raise ValueError("agent identity and prompt exceed transcript limit")
                provider = self._get_provider(agent.provider_name)
                rendered = self._render_prompt(prompt, turns)
                result = provider.generate(
                    ProviderRequest(
                        request_id=f"coord-{uuid4().hex}",
                        prompt=rendered,
                        mode=self._route(prompt),
                    )
                )
                content = getattr(result, "text", getattr(result, "output", None))
                if not isinstance(content, str):
                    raise ValueError("provider returned non-text output")
                content = content[: min(self.max_turn_chars, available)]
                turn = AgentTurn(agent.agent_id, agent.role, content)
                turns.append(turn)
                turn_count += 1
                ignored_proposals += len(getattr(result, "proposed_actions", ()) or ())
                self._trim_transcript(prompt, turns)
        return CoordinationResult(tuple(turns), ignored_proposals)

    def _get_provider(self, provider_name: str) -> Any:
        getter = getattr(self._registry, "get", None)
        provider = getter(provider_name) if callable(getter) else None
        if provider is None and isinstance(self._registry, dict):
            provider = self._registry.get(provider_name)
        if provider is None or not callable(getattr(provider, "generate", None)):
            raise ValueError(f"unknown or invalid provider: {provider_name}")
        return provider

    def _route(self, prompt: str) -> Mode:
        route = getattr(self._router, "route", None)
        if callable(route):
            mode = route(prompt)
            if isinstance(mode, Mode):
                return mode
        return Mode.GENERAL

    def _render_prompt(self, prompt: str, turns: list[AgentTurn]) -> str:
        parts = [f"[user]\n{prompt}"]
        parts.extend(
            f"[{turn.agent_id} | {turn.role}]\n{turn.content}"
            for turn in turns
        )
        return "\n\n".join(parts)

    def _trim_transcript(self, prompt: str, turns: list[AgentTurn]) -> None:
        while turns and len(self._render_prompt(prompt, turns)) > self.max_transcript_chars:
            turns.pop(0)
