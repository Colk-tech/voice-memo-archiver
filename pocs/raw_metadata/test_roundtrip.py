"""Only synthetic databases exercise bounded in-memory verification."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from pocs.raw_metadata import roundtrip
from pocs.sqlite_capture.capture import CaptureError, _Deadline


def _database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('CREATE TABLE "private""table" ("private""field")')
        connection.executemany(
            'INSERT INTO "private""table" VALUES (?)',
            [(None,), (-(2**63),), (2**63 - 1,), (1.5,), ("",), (b"",)],
        )
        connection.execute(
            'INSERT INTO "private""table" VALUES (CAST(X\'6100FF\' AS TEXT))'
        )
        connection.execute("CREATE TABLE empty (value)")
        connection.execute("CREATE VIEW ignored AS SELECT * FROM empty")
        connection.commit()


def test_all_types_and_opaque_text(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.sqlite"
    _database(path)
    result = roundtrip.verify_database(path)
    assert result.cell_types == {
        "null": 1,
        "integer": 2,
        "real": 1,
        "text": 2,
        "blob": 1,
    }
    assert result.total_cells == result.verified_cells == 7
    assert result.roundtrip_verified
    assert result.sqlite_text_encoding == "UTF-8"
    assert result.acquisition_completeness == "UNKNOWN"
    assert not result.disposal_enabled
    assert "private" not in repr(result)


def test_no_tables(tmp_path: Path) -> None:
    path = tmp_path / "empty.sqlite"
    with closing(sqlite3.connect(path)):
        pass
    result = roundtrip.verify_database(path)
    assert result.total_cells == result.verified_cells == 0


@pytest.mark.parametrize("encoding", ["UTF-16le", "UTF-16be"])
def test_utf16_encoding_provenance(tmp_path: Path, encoding: str) -> None:
    path = tmp_path / "utf16.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f"PRAGMA encoding='{encoding}'")
        connection.execute("CREATE TABLE synthetic (value)")
        connection.execute("INSERT INTO synthetic VALUES (?)", ("合成\x00text",))
        connection.commit()
    result = roundtrip.verify_database(path)
    assert result.sqlite_text_encoding == encoding
    assert result.cell_types["text"] == result.verified_cells == 1


def test_unknown_encoding_is_rejected() -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.row_factory = lambda _cursor, _row: ("private-encoding",)
        with pytest.raises(ValueError):
            roundtrip._inspect(connection, _Deadline())


@pytest.mark.parametrize(
    ("bound", "limit"),
    [
        ("MAX_TABLES", 1),
        ("MAX_COLUMNS", 0),
        ("MAX_ROWS", 6),
        ("MAX_CELLS", 6),
        ("MAX_CELL_BYTES", 2),
        ("MAX_TOTAL_BYTES", 18),
    ],
)
def test_bounds_fail_without_partial_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bound: str, limit: int
) -> None:
    path = tmp_path / "synthetic.sqlite"
    _database(path)
    monkeypatch.setattr(roundtrip, bound, limit)
    with pytest.raises(roundtrip.RoundtripError) as error:
        roundtrip.verify_database(path)
    assert str(error.value) == "Isolated typed metadata verification failed"


def test_sanitized_missing_path(tmp_path: Path) -> None:
    with pytest.raises(roundtrip.RoundtripError) as error:
        roundtrip.verify_database(tmp_path / "private-missing")
    assert "private" not in str(error.value)
    assert error.value.__suppress_context__


def test_python_deadline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "synthetic.sqlite"
    _database(path)
    deadline = _Deadline()
    deadline.expires = 0
    with (
        closing(sqlite3.connect(path)) as connection,
        pytest.raises(CaptureError, match="timed out"),
    ):
        roundtrip._inspect(connection, deadline)
    monkeypatch.setattr(roundtrip, "_Deadline", lambda: deadline)
    with pytest.raises(roundtrip.RoundtripError):
        roundtrip.verify_database(path)


def test_sql_deadline(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.sqlite"
    _database(path)
    deadline = _Deadline()
    with closing(sqlite3.connect(path)) as connection:
        connection.set_progress_handler(lambda: 1, 1)
        with pytest.raises(sqlite3.OperationalError, match="interrupted"):
            roundtrip._inspect(connection, deadline)


def test_mismatch_injection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "synthetic.sqlite"
    _database(path)
    monkeypatch.setattr(roundtrip, "decode_value", lambda _: ("blob", b"bad"))
    with pytest.raises(roundtrip.RoundtripError):
        roundtrip.verify_database(path)


def test_exact_bounds_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "synthetic.sqlite"
    _database(path)
    for name, number in {
        "MAX_TABLES": 2,
        "MAX_COLUMNS": 1,
        "MAX_ROWS": 7,
        "MAX_CELLS": 7,
        "MAX_CELL_BYTES": 3,
        "MAX_TOTAL_BYTES": 27,
    }.items():
        monkeypatch.setattr(roundtrip, name, number)
    assert roundtrip.verify_database(path).verified_cells == 7
