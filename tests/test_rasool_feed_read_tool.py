"""Read-only, bounded, and injection-resistance tests for the Rasool feed tool."""
from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from ahmad.core.types import EffectStatus
from ahmad.tools.rasool_feed_read import RasoolFeedReadTool


_SCHEMA = """
CREATE TABLE intel_feed (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    title_original TEXT NOT NULL,
    title_ar TEXT NOT NULL,
    summary_ar TEXT NOT NULL,
    score REAL NOT NULL,
    status TEXT NOT NULL CHECK (status = 'persisted'),
    created_at TEXT NOT NULL,
    persisted_at REAL NOT NULL
);
"""


def _make_db(path, n=5, source="github_trending"):
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    for i in range(n):
        conn.execute(
            "INSERT INTO intel_feed VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                f"id{source}{i}", source, f"https://example.com/{source}/{i}",
                f"title{i}", f"عنوان{i}", "م" * 900, 0.0, "persisted",
                f"2026-10-01T08:0{i}:00Z", 1000.0 + i,
            ),
        )
    conn.commit()
    conn.close()


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "intel_feed.sqlite"
    _make_db(path)
    return path


def test_default_read_is_ordered_and_untrusted(db):
    result = RasoolFeedReadTool(db).run("rasool_feed_read")

    assert result.success
    assert result.effect_status is EffectStatus.NOT_APPLIED
    data = json.loads(result.output)
    assert data["untrusted_content"] is True
    assert data["count"] == 5
    timestamps = [item["created_at"] for item in data["items"]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_limit_and_text_fields_are_bounded(db):
    result = RasoolFeedReadTool(db).run('rasool_feed_read:{"limit": 2}')
    data = json.loads(result.output)

    assert data["count"] == 2
    assert len(data["items"][0]["summary_ar"]) == RasoolFeedReadTool.MAX_FIELD_CHARS


def test_source_filter(tmp_path):
    path = tmp_path / "feed.sqlite"
    _make_db(path, 3, "github_trending")
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO intel_feed VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("x1", "other_src", "https://example.com/o", "t", "ع", "م", 0.0,
         "persisted", "2026-10-01T09:00:00Z", 2000.0),
    )
    conn.commit()
    conn.close()

    result = RasoolFeedReadTool(path).run(
        'rasool_feed_read:{"source": "other_src"}'
    )
    data = json.loads(result.output)

    assert data["count"] == 1
    assert data["items"][0]["source"] == "other_src"


@pytest.mark.parametrize("bad", [
    '{"limit": 0}', '{"limit": 51}', '{"limit": true}', '{"limit": "5"}',
    '{"limit": 1.5}', '{"source": "x\' OR \'1\'=\'1"}', '{"source": "A B"}',
    '{"source": 5}', '{"db": "/etc/passwd"}', '{"path": "x"}',
    '[1,2]', '{bad json',
])
def test_invalid_arguments_are_rejected(db, bad):
    result = RasoolFeedReadTool(db).run(f"rasool_feed_read:{bad}")

    assert not result.success
    assert result.effect_status is EffectStatus.NOT_APPLIED


def test_missing_db_fails_safely(tmp_path):
    result = RasoolFeedReadTool(tmp_path / "missing.sqlite").run(
        "rasool_feed_read"
    )

    assert not result.success
    assert "not found" in result.output


def test_reads_do_not_mutate_database_or_create_sidecars(db, tmp_path):
    before = _sha(db)

    RasoolFeedReadTool(db).run("rasool_feed_read")
    RasoolFeedReadTool(db).run('rasool_feed_read:{"limit": 3}')

    assert _sha(db) == before
    assert not list(tmp_path.glob("*-wal"))
    assert not list(tmp_path.glob("*-shm"))


def test_wrong_schema_returns_failure(tmp_path):
    path = tmp_path / "wrong_schema.sqlite"
    sqlite3.connect(path).close()

    result = RasoolFeedReadTool(path).run("rasool_feed_read")

    assert not result.success
    assert "feed read failed" in result.output
