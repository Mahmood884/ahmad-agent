import sqlite3
from pathlib import Path

import pytest

from ahmad.memory.local_memory import LocalMemoryStore
from ahmad.memory.sqlite_encryption import load_encryption_key, require_sqlcipher
from ahmad.memory.sqlite_migrate import migrate_database
from ahmad.memory.sqlite_store import SQLiteEventStore


@pytest.fixture
def sqlcipher():
    return pytest.importorskip("sqlcipher3.dbapi2")


def test_encryption_key_is_persistent_private_and_validated(tmp_path):
    key_file = tmp_path / "config" / "ahmad" / "encryption.key"

    first = load_encryption_key(key_file)
    second = load_encryption_key(key_file)

    assert len(first) == 32
    assert second == first
    assert key_file.stat().st_mode & 0o777 == 0o600
    assert key_file.read_bytes() == first

    key_file.chmod(0o644)
    with pytest.raises(RuntimeError, match="mode 0600"):
        load_encryption_key(key_file)
    key_file.chmod(0o600)
    key_file.write_bytes(b"short")
    with pytest.raises(RuntimeError, match="exactly 32 bytes"):
        load_encryption_key(key_file)


def test_both_stores_are_encrypted_and_survive_reopen(tmp_path, sqlcipher):
    key_file = tmp_path / "keys" / "encryption.key"
    event_database = tmp_path / "events.db"
    memory_database = tmp_path / "memories.db"

    events = SQLiteEventStore(event_database, key_path=key_file)
    events._connect().close()
    memory = LocalMemoryStore(memory_database, owner_id="uid:test", key_path=key_file)
    memory_id = memory.add("confidential memory")

    reopened_events = SQLiteEventStore(event_database, key_path=key_file)
    reopened_memory = LocalMemoryStore(
        memory_database, owner_id="uid:test", key_path=key_file
    )
    assert reopened_events.read_all() == []
    assert reopened_memory.search("confidential")[0]["id"] == memory_id
    assert event_database.stat().st_mode & 0o777 == 0o600
    assert memory_database.stat().st_mode & 0o777 == 0o600

    for database in (event_database, memory_database):
        with sqlite3.connect(database) as standard_sqlite:
            with pytest.raises(sqlite3.DatabaseError):
                standard_sqlite.execute("SELECT name FROM sqlite_master").fetchall()


def test_sqlite_event_store_reopens_persisted_events(tmp_path, sqlcipher):
    from ahmad.core.events import DecisionEvent
    from ahmad.core.types import Mode, Scope
    from ahmad.governance.policy import PolicyEngine

    database = tmp_path / "events.db"
    key_file = tmp_path / "keys" / "encryption.key"
    decision = PolicyEngine().evaluate("demo:mock", Mode.GENERAL, Scope.PERSONAL)
    event = DecisionEvent.from_decision(
        decision, event_id="encrypted-event", request_id="encrypted-request", timestamp_ms=1
    )
    SQLiteEventStore(database, key_path=key_file).append(event)

    assert SQLiteEventStore(database, key_path=key_file).read(event.event_id) == event.to_dict()


def test_plaintext_database_migrates_and_keeps_verified_backup(tmp_path, sqlcipher):
    database = tmp_path / "legacy.db"
    key_file = tmp_path / "keys" / "encryption.key"
    backup = tmp_path / "legacy.db.plaintext.bak"
    with sqlite3.connect(database) as plaintext:
        plaintext.executescript(
            """
            CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT NOT NULL);
            CREATE INDEX notes_body ON notes(body);
            INSERT INTO notes(body) VALUES ('first note'), ('second note');
            """
        )

    returned_backup = migrate_database(
        database, key_path=key_file, application_stopped=True
    )

    assert returned_backup == backup
    with sqlite3.connect(backup) as preserved_plaintext:
        assert preserved_plaintext.execute("SELECT count(*) FROM notes").fetchone()[0] == 2
        assert preserved_plaintext.execute(
            "SELECT body FROM notes ORDER BY id"
        ).fetchall() == [("first note",), ("second note",)]
        assert preserved_plaintext.execute(
            "SELECT sql FROM sqlite_master WHERE name='notes_body'"
        ).fetchone() is not None
    assert backup.stat().st_mode & 0o777 == 0o600
    with pytest.raises(sqlite3.DatabaseError):
        with sqlite3.connect(database) as standard_sqlite:
            standard_sqlite.execute("SELECT name FROM sqlite_master").fetchall()

    encrypted = sqlcipher.connect(database)
    try:
        encrypted.execute(f'PRAGMA key = "x\'{key_file.read_bytes().hex()}\'"')
        assert encrypted.execute("SELECT count(*) FROM notes").fetchone()[0] == 2
        assert encrypted.execute(
            "SELECT sql FROM sqlite_master WHERE name='notes_body'"
        ).fetchone() is not None
    finally:
        encrypted.close()


def test_migration_never_overwrites_existing_backup(tmp_path, sqlcipher):
    database = tmp_path / "legacy.db"
    backup = tmp_path / "legacy.db.plaintext.bak"
    with sqlite3.connect(database) as plaintext:
        plaintext.execute("CREATE TABLE test_data (value TEXT)")
    backup.write_text("keep me")

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        migrate_database(
            database,
            key_path=tmp_path / "key",
            backup_path=backup,
            application_stopped=True,
        )

    assert backup.read_text() == "keep me"
    with sqlite3.connect(database) as still_plaintext:
        assert still_plaintext.execute(
            "SELECT name FROM sqlite_master WHERE name='test_data'"
        ).fetchone() == ("test_data",)


def test_migration_requires_stopped_database_users(tmp_path):
        database = tmp_path / "legacy.db"
        with sqlite3.connect(database) as plaintext:
            plaintext.execute("CREATE TABLE notes (body TEXT)")

        with pytest.raises(ValueError, match="stop Ahmad"):
            migrate_database(database, key_path=tmp_path / "keys" / "encryption.key")

        assert not Path(f"{database}.plaintext.bak").exists()


def test_migration_refuses_to_replace_database_changed_during_export(
        tmp_path, monkeypatch, sqlcipher
):
        from ahmad.memory import sqlite_migrate

        database = tmp_path / "legacy.db"
        with sqlite3.connect(database) as plaintext:
            plaintext.execute("CREATE TABLE notes (body TEXT NOT NULL)")
            plaintext.execute("INSERT INTO notes VALUES ('before migration')")
        original_export = sqlite_migrate._export_encrypted

        def export_then_mutate(backup, destination, key):
            exported = original_export(backup, destination, key)
            with sqlite3.connect(database) as concurrent_writer:
                concurrent_writer.execute("INSERT INTO notes VALUES ('concurrent write')")
            return exported

        monkeypatch.setattr(sqlite_migrate, "_export_encrypted", export_then_mutate)
        with pytest.raises(RuntimeError, match="changed during migration"):
            migrate_database(
                database,
                key_path=tmp_path / "keys" / "encryption.key",
                application_stopped=True,
            )

        with sqlite3.connect(database) as still_plaintext:
            assert still_plaintext.execute(
                "SELECT body FROM notes ORDER BY rowid"
            ).fetchall() == [("before migration",), ("concurrent write",)]


def test_stores_refuse_plaintext_database_without_fallback(tmp_path, sqlcipher):
    database = tmp_path / "plaintext.db"
    with sqlite3.connect(database) as plaintext:
        plaintext.execute("CREATE TABLE private_data (value TEXT)")

    with pytest.raises(RuntimeError, match="may be plaintext"):
        SQLiteEventStore(database, key_path=tmp_path / "keys" / "encryption.key")
