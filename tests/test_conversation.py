from pathlib import Path

import pytest

from ahmad.core.conversation import ConversationContext, sanitize_conversation_id


def test_render_prompt_unchanged_when_no_history():
    ctx = ConversationContext("t1")
    assert ctx.render_prompt("hello") == "hello"


def test_render_prompt_includes_prior_turns():
    ctx = ConversationContext("t2")
    ctx.add_turn("user", "what is 2+2?")
    ctx.add_turn("assistant", "4")
    rendered = ctx.render_prompt("and 3+3?")
    assert "User: what is 2+2?" in rendered
    assert "Assistant: 4" in rendered
    assert rendered.endswith("User: and 3+3?")


def test_persistence_round_trip(tmp_path: Path):
    path = tmp_path / "conv.jsonl"
    ctx = ConversationContext("t3", path=path)
    ctx.add_turn("user", "hi")
    ctx.add_turn("assistant", "hello")
    assert path.exists()

    reloaded = ConversationContext("t3", path=path)
    assert len(reloaded) == 2
    assert reloaded.render_prompt("next") == "User: hi\nAssistant: hello\nUser: next"


def test_corrupted_line_is_skipped(tmp_path: Path):
    path = tmp_path / "conv.jsonl"
    path.write_text('{"role": "user", "content": "ok", "timestamp": 1.0}\nNOT-JSON\n', encoding="utf-8")
    ctx = ConversationContext("t4", path=path)
    assert len(ctx) == 1


def test_max_chars_drops_oldest_turns():
    ctx = ConversationContext("t5", max_chars=40)
    for i in range(10):
        ctx.add_turn("user", f"message number {i}")
        ctx.add_turn("assistant", f"reply number {i}")
    rendered = ctx.render_prompt("final")
    assert "message number 0" not in rendered
    assert rendered.endswith("User: final")


@pytest.mark.parametrize("bad_id", ["../escape", "a/b", "", "x" * 200, "has space"])
def test_sanitize_rejects_invalid_ids(bad_id):
    with pytest.raises(ValueError):
        sanitize_conversation_id(bad_id)


def test_sanitize_accepts_valid_ids():
    assert sanitize_conversation_id("default") == "default"
    assert sanitize_conversation_id("session_123-abc") == "session_123-abc"
