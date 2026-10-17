"""Explicit DB/WAL copying; destination protection is the operator's obligation."""

import os
import sqlite3
import stat
from contextlib import ExitStack, closing
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from pocs.sqlite_capture.wal import WalError, validate_wal

MAX_BYTES = 64 * 1024 * 1024


class CaptureError(Exception):
    """Fixed diagnostic; never carries source names, rows or SQLite errors."""


class _Deadline:
    def __init__(self) -> None:
        self.expires = monotonic() + 5

    def backup(self, _status: int, _remaining: int, _total: int) -> None:
        if monotonic() >= self.expires:
            raise CaptureError("Isolated inspection timed out")

    def query(self) -> int:
        return int(monotonic() >= self.expires)


@dataclass(frozen=True)
class CaptureEvidence:
    wal_present: bool
    raw_reads_equal: bool
    isolated_quick_check_ok: bool
    schema_objects: int
    tables: int
    columns: int
    id_hint_columns: int
    declared_type_counts: dict[str, int]
    acquisition_completeness: str = "UNKNOWN"
    snapshot_consistency: str = "unknown"
    disposal_enabled: bool = False


def _signature(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    data = bytearray()
    while chunk := os.read(descriptor, min(1024 * 1024, MAX_BYTES + 1 - len(data))):
        data.extend(chunk)
        if len(data) > MAX_BYTES:
            raise CaptureError("Source file exceeds capture bound")
    return bytes(data)


def _raw_pair(database: Path) -> tuple[bytes, bytes | None]:
    with ExitStack() as stack:
        parent = os.open(database.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, parent)
        names = (database.name, database.name + "-wal")
        files: dict[str, int] = {}
        for name in names:
            try:
                descriptor = os.open(
                    name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
                )
            except FileNotFoundError:
                if name == database.name:
                    raise CaptureError("Source database is missing") from None
                continue
            stack.callback(os.close, descriptor)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                raise CaptureError("Source file is unsupported or exceeds bound")
            files[name] = descriptor
        initial = {name: _signature(os.fstat(fd)) for name, fd in files.items()}

        def validate() -> None:
            try:
                os.stat(
                    database.name + "-journal", dir_fd=parent, follow_symlinks=False
                )
            except FileNotFoundError:
                pass
            else:
                raise CaptureError("Rollback journal is unsupported")
            for name in names:
                try:
                    current = _signature(
                        os.stat(name, dir_fd=parent, follow_symlinks=False)
                    )
                except FileNotFoundError:
                    if name in files:
                        raise CaptureError("Source changed during capture") from None
                    continue
                if name not in files or current != initial[name]:
                    raise CaptureError("Source changed during capture")
            for name, fd in files.items():
                if _signature(os.fstat(fd)) != initial[name]:
                    raise CaptureError("Source changed during capture")

        validate()
        first = {name: _read(fd) for name, fd in files.items()}
        validate()
        second = {name: _read(fd) for name, fd in files.items()}
        validate()
        if first != second:
            raise CaptureError("Source changed during capture")
        return first[database.name], first.get(names[1])


def _schema(
    connection: sqlite3.Connection,
) -> tuple[int, int, int, int, dict[str, int]]:
    objects = connection.execute("SELECT count(*) FROM sqlite_schema").fetchone()[0]
    tables = connection.execute(
        "SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name"
    ).fetchall()
    columns = 0
    ids = 0
    types = dict.fromkeys(("integer", "real", "text", "blob", "numeric", "other"), 0)
    for (name,) in tables:
        # PRAGMA's table-valued function accepts a bound identifier as data.
        for column in connection.execute(
            "SELECT name, type FROM pragma_table_xinfo(?)", (name,)
        ):
            columns += 1
            field, declared = column
            ids += int(
                any(
                    hint in field.lower()
                    for hint in ("uuid", "uniqueid", "recordingid")
                )
            )
            label = declared.lower()
            types[label if label in types else "other"] += 1
    return objects, len(tables), columns, ids, types


def capture_database(database: Path, protected_parent: Path) -> CaptureEvidence:
    """Caller must provide an encrypted, isolated parent outside source/repo.

    Creates a new 0700 child; never overwrites. Source SHM is not opened/copied.
    Two equal reads detect some races, not ABA or cross-artifact atomicity.
    Copies remain for operator cleanup on the protected volume, also on failure.
    """
    try:
        main, wal = _raw_pair(database)
        validate_wal(main, wal or b"")
        destination = protected_parent / "capture"
        destination.mkdir(mode=0o700)
        target = destination / "source.sqlite"
        with target.open("xb") as output:
            output.write(main)
        target.chmod(0o600)
        if wal is not None:
            target_wal = destination / "source.sqlite-wal"
            with target_wal.open("xb") as output:
                output.write(wal)
            target_wal.chmod(0o600)
        with (
            closing(
                sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=1)
            ) as copy,
            closing(sqlite3.connect(":memory:")) as snapshot,
        ):
            copy.execute("PRAGMA trusted_schema=OFF")
            deadline = _Deadline()
            copy.backup(snapshot, pages=128, progress=deadline.backup, sleep=0.01)
            snapshot.set_progress_handler(deadline.query, 1000)
            snapshot.execute("PRAGMA trusted_schema=OFF")
            snapshot.execute("PRAGMA temp_store=MEMORY")
            if snapshot.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise CaptureError("Isolated database integrity check failed")
            objects, tables, columns, ids, types = _schema(snapshot)
            if not objects:
                raise CaptureError("Isolated database schema is empty")
        return CaptureEvidence(
            wal is not None, True, True, objects, tables, columns, ids, types
        )
    except OSError, sqlite3.Error, ValueError, WalError:
        raise CaptureError("Isolated capture failed") from None
