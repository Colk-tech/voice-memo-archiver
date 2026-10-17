"""Synthetic SQLite contracts; never discover or open a real account."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from voice_memo_archiver.infrastructure.source.sqlite_probe import (
    ProbeError,
    _Deadline,
    probe_database,
)


def test_wal_snapshot_preserves_source_and_omits_private_data(tmp_path: Path) -> None:
    path = tmp_path / "音声 ?#%.sqlite"
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE recording (id TEXT, secret BLOB)")
        writer.commit()
        before = probe_database(path)
        writer.execute("CREATE TABLE private_title (value TEXT DEFAULT 'secret')")
        writer.execute("INSERT INTO recording VALUES ('private-id', X'00FF')")
        writer.commit()
        db_bytes = path.read_bytes()
        wal_bytes = path.with_suffix(".sqlite-wal").read_bytes()
        after = probe_database(path)
        assert after.schema_objects == 2
        assert after.schema_sha256 != before.schema_sha256
        assert after == probe_database(path)
        assert path.read_bytes() == db_bytes
        assert path.with_suffix(".sqlite-wal").read_bytes() == wal_bytes
        assert writer.execute("SELECT count(*) FROM recording").fetchone() == (1,)
        assert "private" not in repr(after)
        assert "secret" not in repr(after)


def test_row_changes_do_not_change_schema_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / "source.sqlite"
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("CREATE TABLE recording (id TEXT)")
        writer.commit()
        before = probe_database(path)
        writer.execute("INSERT INTO recording VALUES ('sensitive')")
        writer.commit()
        assert probe_database(path) == before


@pytest.mark.parametrize("kind", ["missing", "corrupt", "directory"])
def test_invalid_source_is_sanitized(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "private-source"
    if kind == "corrupt":
        path.write_bytes(b"not a database")
    elif kind == "directory":
        path.mkdir()
    with pytest.raises(ProbeError, match="^SQLite probe failed$"):
        probe_database(path)
    if kind == "missing":
        assert not path.exists()


def test_empty_database_is_not_a_valid_inventory(tmp_path: Path) -> None:
    path = tmp_path / "empty.sqlite"
    path.touch()
    with pytest.raises(ProbeError, match="No schema objects"):
        probe_database(path)


def test_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    deadline = _Deadline()
    monkeypatch.setattr(
        "voice_memo_archiver.infrastructure.source.sqlite_probe.monotonic",
        lambda: deadline.expires - 1,
    )
    deadline.check(0, 1, 2)
    monkeypatch.setattr(
        "voice_memo_archiver.infrastructure.source.sqlite_probe.monotonic",
        lambda: deadline.expires,
    )
    with pytest.raises(ProbeError, match="timed out"):
        deadline.check(0, 1, 2)


def test_backup_timeout_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "source.sqlite"
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("CREATE TABLE recording (id TEXT)")

    def timeout(self: _Deadline, status: int, remaining: int, total: int) -> None:
        raise ProbeError("SQLite snapshot timed out")

    with monkeypatch.context() as patch:
        patch.setattr(_Deadline, "check", timeout)
        with pytest.raises(ProbeError, match="timed out"):
            probe_database(path)
    assert probe_database(path).schema_objects == 1


def test_source_connection_rejects_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "source.sqlite"
    real_connect = sqlite3.connect
    with closing(real_connect(path)) as writer:
        writer.execute("CREATE TABLE recording (id TEXT)")
    read_only_connections = 0

    def checked_connect(
        database: str, *, uri: bool = False, timeout: float = 5
    ) -> sqlite3.Connection:
        nonlocal read_only_connections
        connection = real_connect(database, uri=uri, timeout=timeout)
        if uri:
            read_only_connections += 1
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                connection.execute("CREATE TABLE forbidden (id TEXT)")
        return connection

    monkeypatch.setattr(sqlite3, "connect", checked_connect)
    assert probe_database(path).schema_objects == 1
    assert read_only_connections == 1
