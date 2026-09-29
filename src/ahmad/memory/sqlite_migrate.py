"""Safely convert a plaintext SQLite database to SQLCipher format."""
from __future__ import annotations

import argparse
import os
import sqlite3
import stat
import sys
import uuid
from pathlib import Path
from typing import Any

from ahmad.memory.sqlite_encryption import load_encryption_key, require_sqlcipher


def _snapshot(connection: Any) -> tuple[list[tuple], dict[str, int]]:
    schema = connection.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """
    ).fetchall()
    tables = connection.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    counts = {}
    for (table_name,) in tables:
        quoted_name = '"' + table_name.replace('"', '""') + '"'
        counts[table_name] = int(
            connection.execute(f"SELECT count(*) FROM {quoted_name}").fetchone()[0]
        )
    return [tuple(row) for row in schema], counts


def _file_signature(source: Path) -> tuple[tuple[str, int, int, int, int] | None, ...]:
    signature = []
    for suffix in ("", "-wal", "-shm", "-journal"):
        artifact = Path(f"{source}{suffix}")
        try:
            metadata = artifact.stat()
        except FileNotFoundError:
            signature.append(None)
        else:
            signature.append(
                (
                    suffix,
                    metadata.st_ino,
                    metadata.st_size,
                    metadata.st_mtime_ns,
                    metadata.st_ctime_ns,
                )
            )
    return tuple(signature)


def _make_plaintext_backup(
    source: Path, backup: Path
) -> tuple[tuple[list[tuple], dict[str, int]], tuple[tuple[str, int, int, int, int] | None, ...]]:
    source_connection = None
    backup_connection = None
    backup_created = False
    try:
        descriptor = os.open(
            backup,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        os.close(descriptor)
        backup_created = True
        source_connection = sqlite3.connect(source, timeout=30)
        checkpoint = source_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint and checkpoint[0]:
            raise RuntimeError(
                "could not checkpoint the source database; close other database users "
                "and retry migration"
            )
        source_snapshot = _snapshot(source_connection)
        backup_connection = sqlite3.connect(backup, timeout=30)
        source_connection.backup(backup_connection)
        backup_connection.close()
        backup_connection = None
        backup.chmod(0o600)
        with sqlite3.connect(backup, timeout=30) as backup_read:
            backup_snapshot = _snapshot(backup_read)
        if source_snapshot != backup_snapshot:
            raise RuntimeError("plaintext backup verification failed; source may have changed")
        return backup_snapshot, _file_signature(source)
    except sqlite3.DatabaseError as exc:
        if backup_connection is not None:
            backup_connection.close()
            backup_connection = None
        if source_connection is not None:
            source_connection.close()
            source_connection = None
        if backup_created:
            for suffix in ("", "-wal", "-shm", "-journal"):
                artifact = Path(f"{backup}{suffix}")
                if artifact.exists():
                    artifact.unlink()
        raise RuntimeError(
            "source is not a readable plaintext SQLite database; migration expects "
            "an existing plaintext database"
        ) from exc
    except Exception:
        if backup_connection is not None:
            backup_connection.close()
            backup_connection = None
        if source_connection is not None:
            source_connection.close()
            source_connection = None
        if backup_created:
            for suffix in ("", "-wal", "-shm", "-journal"):
                artifact = Path(f"{backup}{suffix}")
                if artifact.exists():
                    artifact.unlink()
        raise
    finally:
        if backup_connection is not None:
            backup_connection.close()
        if source_connection is not None:
            source_connection.close()


def _export_encrypted(
    plaintext_backup: Path, destination: Path, key: bytes
) -> tuple[list[tuple], dict[str, int]]:
    driver = require_sqlcipher()
    connection = driver.connect(plaintext_backup, timeout=30)
    try:
        connection.execute(
            f'ATTACH DATABASE ? AS encrypted KEY "x\'{key.hex()}\'"',
            (str(destination),),
        )
        connection.execute("SELECT sqlcipher_export('encrypted')").fetchone()
        connection.execute("DETACH DATABASE encrypted")
    finally:
        connection.close()

    encrypted = driver.connect(destination, timeout=30)
    try:
        encrypted.execute(f'PRAGMA key = "x\'{key.hex()}\'"')
        return _snapshot(encrypted)
    finally:
        encrypted.close()


def migrate_database(
    database_path: str | Path,
    *,
    key_path: str | Path | None = None,
    backup_path: str | Path | None = None,
    application_stopped: bool = False,
) -> Path:
    """Encrypt a plaintext database in place and return its preserved backup path."""
    if not application_stopped:
        raise ValueError(
            "stop Ahmad and every process using this database before migration, "
            "then confirm with application_stopped=True"
        )
    source = Path(database_path).expanduser().absolute()
    try:
        source_metadata = source.lstat()
    except OSError as exc:
        raise ValueError(f"cannot inspect source database: {source}") from exc
    if not stat.S_ISREG(source_metadata.st_mode):
        raise ValueError(f"source database must be a regular file: {source}")
    backup = (
        Path(backup_path).expanduser().absolute()
        if backup_path is not None
        else source.with_name(source.name + ".plaintext.bak")
    )
    if backup == source:
        raise ValueError("plaintext backup path must differ from the source database")
    if backup.exists() or backup.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing plaintext backup: {backup}")
    backup.parent.mkdir(parents=True, exist_ok=True)
    require_sqlcipher()
    key = load_encryption_key(key_path)

    temporary = source.with_name(f".{source.name}.{uuid.uuid4().hex}.sqlcipher")
    temporary_created = False
    try:
        snapshot, source_signature = _make_plaintext_backup(source, backup)
        descriptor = os.open(
            temporary,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        temporary_created = True
        os.close(descriptor)
        _exported_schema, exported_counts = _export_encrypted(backup, temporary, key)
        cipher = require_sqlcipher()
        verification = cipher.connect(temporary, timeout=30)
        try:
            verification.execute(f'PRAGMA key = "x\'{key.hex()}\'"')
            verification_snapshot = _snapshot(verification)
        finally:
            verification.close()
        if verification_snapshot != snapshot:
            raise RuntimeError("encrypted database verification failed; source was not replaced")
        if exported_counts != snapshot[1]:
            raise RuntimeError("encrypted row-count verification failed; source was not replaced")
        if _file_signature(source) != source_signature:
            raise RuntimeError(
                "source database changed during migration; source was not replaced. "
                "Stop all database writers and retry."
            )

        temporary.chmod(0o600)
        temporary.replace(source)
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(f"{source}{suffix}")
            if sidecar.exists():
                sidecar.unlink()
        return backup
    except Exception:
        if temporary_created:
            for suffix in ("", "-wal", "-shm", "-journal"):
                artifact = Path(f"{temporary}{suffix}")
                if artifact.exists():
                    artifact.unlink()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Encrypt a plaintext SQLite database with SQLCipher."
    )
    parser.add_argument("database", type=Path, help="plaintext SQLite database to convert")
    parser.add_argument(
        "--key-file",
        type=Path,
        help="SQLCipher key file (default: ~/.config/ahmad/encryption.key)",
    )
    parser.add_argument(
        "--backup-file",
        type=Path,
        help="plaintext backup path (default: DATABASE.plaintext.bak)",
    )
    parser.add_argument(
        "--confirm-application-stopped",
        action="store_true",
        help="confirm Ahmad and all processes using this database are stopped",
    )
    args = parser.parse_args(argv)
    try:
        backup = migrate_database(
            args.database,
            key_path=args.key_file,
            backup_path=args.backup_file,
            application_stopped=args.confirm_application_stopped,
        )
    except Exception as exc:
        print(f"SQLite migration failed: {exc}", file=sys.stderr)
        return 1
    print(f"Encrypted database successfully; plaintext backup: {backup}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
