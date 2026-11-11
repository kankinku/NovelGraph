"""SQLite online backup and create-only restore, confined to private data roots.

Never replace the live ledger or treat a backup as user approval.
"""
from __future__ import annotations

from .privacy import private_path

from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile


def _validated_database(path: Path, *, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} database does not exist or is not a regular file")
    mode = path.stat().st_mode
    if not private_path(path):
        raise ValueError(f"{label} database must be private")
    if os.name != "nt" and not mode & 0o400:
        raise ValueError(f"{label} database must be owner-readable")
    return path


def _destination(raw: str, root: Path) -> Path:
    target = Path(raw).absolute()
    if target.suffix != ".sqlite" or target.name in (".", ".."):
        raise ValueError("database output must be a .sqlite file")
    if target.is_symlink() or target.exists():
        raise ValueError("database output already exists; overwrite is forbidden")
    parent = target.parent.resolve(strict=True)
    if not parent.is_relative_to(root):
        raise ValueError("database output must be under the private data root")
    if not parent.is_dir() or not private_path(parent):
        raise ValueError("database output parent must be private")
    return parent / target.name


def _input_backup(raw: str, root: Path) -> Path:
    original = Path(raw).absolute()
    if original.is_symlink():
        raise ValueError("backup database symlinks are forbidden")
    path = original.resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError("backup database must be under private data root")
    _validated_database(path, label="backup")
    if path.suffix != ".sqlite":
        raise ValueError("backup database must have a .sqlite suffix")
    return path


def _check_ledger(db: sqlite3.Connection) -> None:
    """Fail closed for invalid SQLite structures, foreign keys or NovelGraph schema."""
    check = db.execute("PRAGMA integrity_check").fetchall()
    if check != [("ok",)]:
        raise ValueError("database integrity_check failed")
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("database foreign key integrity failed")
    names = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    if not {"episodes", "candidates"}.issubset(names):
        raise ValueError("database is not a NovelGraph ledger")


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def _create_snapshot(source: Path, output: Path) -> dict:
    """Use SQLite Online Backup API; publish only a fully verified new file."""
    fd, pending = tempfile.mkstemp(
        prefix=f".{output.name}.pending-", suffix=".tmp", dir=output.parent
    )
    os.close(fd)
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
            _check_ledger(src)
            with closing(sqlite3.connect(pending)) as dest:
                src.backup(dest)
                _check_ledger(dest)
        with open(pending, "rb") as snapshot:
            os.fsync(snapshot.fileno())
        digest = _digest(Path(pending))
        # Atomic, create-only publication. Never rename over an existing file.
        try:
            os.link(pending, output)
        except FileExistsError as exc:
            raise ValueError("database output already exists; overwrite is forbidden") from exc
        dir_fd = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return {
            "snapshot_sha256": digest,
            "integrity": "ok",
            "created_only": True,
            "read_only_source": True,
            "world_state_mutations": 0,
            "source_quotes_included": False,
        }
    finally:
        # A SIGKILL may leave an unpublished hidden temp file, never a visible
        # incomplete output. Manual cleanup is permitted only after inspection.
        Path(pending).unlink(missing_ok=True)


def backup_database(root: Path, output: str) -> dict:
    source = _validated_database(root / "novelgraph.sqlite", label="source")
    target = _destination(output, root)
    return {"operation": "backup", **_create_snapshot(source, target)}


def restore_database(root: Path, backup: str, output: str) -> dict:
    source = _input_backup(backup, root)
    target = _destination(output, root)
    return {"operation": "restore_to_new_file", **_create_snapshot(source, target)}
