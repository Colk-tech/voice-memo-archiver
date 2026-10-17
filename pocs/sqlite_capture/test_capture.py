"""Synthetic-only capture fault injection; never accesses a live source."""

import functools
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

import pytest

from pocs.sqlite_capture import capture


def make_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "CREATE TABLE private_name (uuid TEXT, n INTEGER, r REAL, "
            "b BLOB, x NUMERIC, odd CUSTOM)"
        )
        connection.commit()


def test_capture_schema_and_privacy(tmp_path: Path) -> None:
    database = tmp_path / "private.sqlite"
    make_database(database)
    before = database.read_bytes()
    result = capture.capture_database(database, tmp_path)
    assert result.tables == 1
    assert result.columns == 6
    assert result.id_hint_columns == 1
    assert result.declared_type_counts == dict.fromkeys(
        ("integer", "real", "text", "blob", "numeric", "other"), 1
    )
    assert result.acquisition_completeness == "UNKNOWN"
    assert result.snapshot_consistency == "unknown"
    assert result.disposal_enabled is False
    assert not result.wal_present
    assert database.read_bytes() == before
    assert "private" not in repr(result)
    assert (tmp_path / "capture").stat().st_mode & 0o777 == 0o700
    assert (tmp_path / "capture/source.sqlite").stat().st_mode & 0o777 == 0o600


def test_missing_source(tmp_path: Path) -> None:
    with pytest.raises(capture.CaptureError, match="Source database is missing"):
        capture._raw_pair(tmp_path / "missing")


@pytest.mark.parametrize("kind", ["directory", "symlink", "fifo", "oversize"])
def test_reject_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    database = tmp_path / "source"
    if kind == "directory":
        database.mkdir()
    elif kind == "symlink":
        database.symlink_to(tmp_path / "other")
    elif kind == "fifo":
        os.mkfifo(database)
    else:
        database.write_bytes(b"ab")
        monkeypatch.setattr(capture, "MAX_BYTES", 1)
    with pytest.raises((capture.CaptureError, OSError)):
        capture._raw_pair(database)


def test_read_growth_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "source"
    database.write_bytes(b"ab")
    monkeypatch.setattr(capture, "MAX_BYTES", 1)
    descriptor = os.open(database, os.O_RDONLY)
    try:
        with pytest.raises(capture.CaptureError, match="exceeds capture bound"):
            capture._read(descriptor)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("change", ["remove", "add", "replace", "modify"])
def test_source_races(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    database = tmp_path / "source"
    database.write_bytes(b"db")
    wal = tmp_path / "source-wal"
    if change != "add":
        wal.write_bytes(b"wal")
    original = capture._read
    changed = False

    def changing_read(descriptor: int) -> bytes:
        nonlocal changed
        value = original(descriptor)
        if not changed:
            changed = True
            if change == "remove":
                wal.unlink()
            elif change == "add":
                wal.write_bytes(b"wal")
            elif change == "replace":
                replacement = tmp_path / "replacement"
                replacement.write_bytes(b"wal")
                replacement.replace(wal)
            else:
                wal.write_bytes(b"changed")
        return value

    monkeypatch.setattr(capture, "_read", changing_read)
    with pytest.raises(capture.CaptureError, match="Source changed"):
        capture._raw_pair(database)


def test_raw_bytes_differ(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = tmp_path / "source"
    database.write_bytes(b"db")
    calls = 0

    def read_different(_descriptor: int) -> bytes:
        nonlocal calls
        calls += 1
        return b"first" if calls == 1 else b"second"

    monkeypatch.setattr(capture, "_read", read_different)
    with pytest.raises(capture.CaptureError, match="Source changed"):
        capture._raw_pair(database)


def test_fstat_change_and_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "source"
    database.write_bytes(b"db")
    original = os.fstat
    calls = 0
    descriptors: list[int] = []

    def changed_stat(descriptor: int) -> os.stat_result:
        nonlocal calls
        descriptors.append(descriptor)
        calls += 1
        info = original(descriptor)
        if calls == 3:
            values = list(info)
            values[6] += 1
            return os.stat_result(values)
        return info

    monkeypatch.setattr(os, "fstat", changed_stat)
    with pytest.raises(capture.CaptureError, match="Source changed"):
        capture._raw_pair(database)
    for descriptor in set(descriptors):
        with pytest.raises(OSError):
            original(descriptor)


@pytest.mark.parametrize("payload", [b"not sqlite", b""])
def test_invalid_and_empty_database(tmp_path: Path, payload: bytes) -> None:
    database = tmp_path / "source"
    database.write_bytes(payload)
    with pytest.raises(capture.CaptureError) as error:
        capture.capture_database(database, tmp_path)
    assert "source" not in str(error.value).lower()
    assert str(tmp_path) not in str(error.value)


def test_existing_destination_is_not_overwritten(tmp_path: Path) -> None:
    database = tmp_path / "source"
    make_database(database)
    destination = tmp_path / "capture"
    destination.mkdir()
    marker = destination / "marker"
    marker.write_bytes(b"unchanged")
    with pytest.raises(capture.CaptureError, match="Isolated capture failed"):
        capture.capture_database(database, tmp_path)
    assert marker.read_bytes() == b"unchanged"


def test_empty_schema(tmp_path: Path) -> None:
    database = tmp_path / "source"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA user_version=1")
    with pytest.raises(capture.CaptureError, match="schema is empty"):
        capture.capture_database(database, tmp_path)


def test_rollback_journal_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "source"
    make_database(database)
    (tmp_path / "source-journal").touch()
    with pytest.raises(capture.CaptureError, match="Rollback journal"):
        capture.capture_database(database, tmp_path)


def test_invalid_wal_is_not_silently_ignored(tmp_path: Path) -> None:
    database = tmp_path / "source"
    make_database(database)
    (tmp_path / "source-wal").write_bytes(b"invalid")
    with pytest.raises(capture.CaptureError, match="Isolated capture failed"):
        capture.capture_database(database, tmp_path)
    assert not (tmp_path / "capture").exists()


@pytest.mark.parametrize("empty", [False, True])
def test_quick_check_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, empty: bool
) -> None:
    database = tmp_path / "source"
    make_database(database)

    class FailedCheck(sqlite3.Connection):
        def execute(self, sql: str, parameters: object = (), /) -> sqlite3.Cursor:
            if sql == "PRAGMA quick_check":
                sql = "SELECT 'private failure'" + (" WHERE 0" if empty else "")
            return super().execute(
                sql, cast(tuple[str | int | float | bytes | None, ...], parameters)
            )

    monkeypatch.setattr(
        sqlite3,
        "connect",
        functools.partial(sqlite3.connect, factory=FailedCheck),
    )
    with pytest.raises(capture.CaptureError, match="integrity check failed"):
        capture.capture_database(database, tmp_path)


def test_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 0.0
    monkeypatch.setattr(capture, "monotonic", lambda: now)
    deadline = capture._Deadline()
    deadline.backup(0, 1, 1)
    assert deadline.query() == 0
    now = 5.0
    assert deadline.query() == 1
    with pytest.raises(capture.CaptureError, match="timed out"):
        deadline.backup(0, 1, 1)


def test_wal_copy_preserves_committed_schema(tmp_path: Path) -> None:
    database = tmp_path / "source"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE private_fixture (recordingid TEXT)")
        connection.commit()
        before = {
            suffix: Path(str(database) + suffix).read_bytes()
            for suffix in ("", "-wal", "-shm")
        }
        result = capture.capture_database(database, tmp_path)
        assert result.wal_present
        assert result.tables == result.columns == result.id_hint_columns == 1
        for suffix, data in before.items():
            assert Path(str(database) + suffix).read_bytes() == data
