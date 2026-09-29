"""Conversation context — bounded multi-turn history for provider requests.

Hermes CLI (`hermes chat -q ... -Q`) is stateless per invocation: each call
starts the model with no memory of prior turns. ConversationContext renders
a bounded transcript that AhmadRuntime prepends to a provider request when
prior turns exist, so the same governed request path gains conversational
continuity without any provider-specific state.

Design notes:
- Provider-agnostic: lives in `core`, not `providers`.
- Append-only JSONL persistence, same graceful-degradation policy as
  MemoryStore (corrupted lines are skipped, not fatal).
- `max_turns` / `max_chars` bound the rendered transcript so it can never
  silently exceed a provider's context_limit; oldest turns are dropped
  first.
- With zero history, render_prompt returns the prompt unchanged — a fresh
  conversation behaves exactly like the previous stateless call.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("ahmad.conversation")

_VALID_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def sanitize_conversation_id(conversation_id: str) -> str:
    """Guard against path traversal — conversation_id becomes a filename."""
    if not isinstance(conversation_id, str) or not _VALID_ID.match(conversation_id):
        raise ValueError(
            "conversation_id must be 1-128 chars of [A-Za-z0-9_-]: "
            f"{conversation_id!r}"
        )
    return conversation_id


@dataclass(frozen=True)
class Turn:
    role: str  # "user" | "assistant"
    content: str
    timestamp: float

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content, "timestamp": self.timestamp}

    @classmethod
    def from_dict(cls, data: dict) -> "Turn":
        return cls(role=data["role"], content=data["content"], timestamp=data["timestamp"])


class ConversationContext:
    """Bounded, append-only turn history for one conversation."""

    def __init__(
        self,
        conversation_id: str,
        *,
        path: Path | None = None,
        max_turns: int = 40,
        max_chars: int = 12_000,
    ) -> None:
        self.conversation_id = sanitize_conversation_id(conversation_id)
        self.path = path
        self.max_turns = max_turns
        self.max_chars = max_chars
        self._turns: list[Turn] = []
        if self.path is not None:
            self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    self._turns.append(Turn.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError, TypeError) as exc:
                    logger.warning(
                        "Skipping corrupted conversation line %d in %s: %s",
                        line_no, self.path, exc,
                    )

    def add_turn(self, role: str, content: str) -> None:
        if role not in ("user", "assistant"):
            raise ValueError(f"invalid role: {role}")
        if not isinstance(content, str):
            raise ValueError("turn content must be a string")
        turn = Turn(role=role, content=content, timestamp=time.time())
        self._turns.append(turn)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(turn.to_dict(), ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())

    def render_prompt(self, next_user_prompt: str) -> str:
        """Bounded history + new prompt as one transcript; unchanged if empty."""
        if not self._turns:
            return next_user_prompt

        def _build(turns: list[Turn]) -> str:
            lines = [f"{'User' if t.role == 'user' else 'Assistant'}: {t.content}" for t in turns]
            lines.append(f"User: {next_user_prompt}")
            return "\n".join(lines)

        history = self._turns[-self.max_turns:]
        transcript = _build(history)
        while len(transcript) > self.max_chars and len(history) > 1:
            history = history[1:]
            transcript = _build(history)
        return transcript

    def clear(self) -> None:
        self._turns = []

    def __len__(self) -> int:
        return len(self._turns)
