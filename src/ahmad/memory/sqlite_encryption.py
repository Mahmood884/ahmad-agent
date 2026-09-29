"""SQLCipher connections and per-user encryption-key handling for SQLite stores."""
from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path
from typing import Any

try:
    from sqlcipher3 import dbapi2 as sqlcipher
except ImportError as exc:  # pragma: no cover - exercised when the required extra is absent
    sqlcipher = None
    _SQLCIPHER_IMPORT_ERROR = exc
else:
    _SQLCIPHER_IMPORT_ERROR = None


KEY_BYTES = 32
DEFAULT_KEY_PATH = Path.home() / ".config" / "ahmad" / "encryption.key"


def require_sqlcipher() -> Any:
    if sqlcipher is None:
        raise RuntimeError(
            "SQLCipher is required for encrypted SQLite persistence; install the "
            "'ahmad-agent' package dependencies (sqlcipher3-binary)."
        ) from _SQLCIPHER_IMPORT_ERROR
    return sqlcipher


def load_encryption_key(path: str | Path | None = None) -> bytes:
    """Create or securely read the persistent, per-user SQLCipher key."""
    key_path = Path(path).expanduser() if path is not None else DEFAULT_KEY_PATH
    key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(key_path, flags)
    except FileNotFoundError:
        temporary = key_path.with_name(f".{key_path.name}.{secrets.token_hex(8)}.tmp")
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            key = secrets.token_bytes(KEY_BYTES)
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(key)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, key_path, follow_symlinks=False)
            except FileExistsError:
                pass
            finally:
                temporary.unlink()
            directory = os.open(
                key_path.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
            )
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            descriptor = os.open(key_path, flags)
        except OSError as exc:
            if temporary.exists():
                temporary.unlink()
            raise RuntimeError(f"cannot safely create encryption key at {key_path}") from exc
    except OSError as exc:
        raise RuntimeError(f"cannot safely read encryption key at {key_path}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(f"encryption key must be a regular file: {key_path}")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise RuntimeError(f"encryption key must be owned by the current user: {key_path}")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RuntimeError(f"encryption key must have mode 0600: {key_path}")
        if metadata.st_size != KEY_BYTES:
            raise RuntimeError(
                f"encryption key must be exactly {KEY_BYTES} bytes: {key_path}"
            )
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            key = stream.read(KEY_BYTES + 1)
        if len(key) != KEY_BYTES:
            raise RuntimeError(
                f"encryption key must be exactly {KEY_BYTES} bytes: {key_path}"
            )
        return key
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _ensure_private_database_file(path: Path) -> None:
    if path.exists() or path.is_symlink():
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise RuntimeError(f"cannot inspect SQLite database file {path}") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(f"SQLite database path must be a regular file: {path}")
    else:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            return _ensure_private_database_file(path)
        except OSError as exc:
            raise RuntimeError(f"cannot safely create SQLite database file {path}") from exc
        else:
            os.close(descriptor)


def connect_encrypted(
    path: str | Path,
    key: bytes,
    *,
    timeout: float,
    row_factory: Any = None,
) -> Any:
    """Open a database only after applying and validating its encryption key."""
    driver = require_sqlcipher()
    database_path = Path(path)
    _ensure_private_database_file(database_path)
    try:
        connection = driver.connect(database_path, timeout=timeout)
    except driver.DatabaseError as exc:
        raise RuntimeError(f"cannot open encrypted SQLite database {database_path}") from exc
    try:
        connection.execute(f'PRAGMA key = "x\'{key.hex()}\'"')
        connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except driver.DatabaseError as exc:
        connection.close()
        message = str(exc).lower()
        if any(text in message for text in ("not a database", "malformed")):
            raise RuntimeError(
                f"cannot decrypt SQLite database {database_path}; it may be plaintext "
                "or encrypted with a different key. Use the SQLite migration command "
                "for existing plaintext databases."
            ) from exc
        raise
    if row_factory is not None:
        connection.row_factory = row_factory
    try:
        database_path.chmod(0o600)
    except OSError as exc:
        connection.close()
        raise RuntimeError(f"cannot secure SQLite database permissions for {database_path}") from exc
    return connection
