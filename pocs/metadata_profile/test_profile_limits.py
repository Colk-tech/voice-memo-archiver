"""Synthetic boundary, typing, and privacy checks for metadata aggregates."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from pocs.metadata_profile import profile
from pocs.metadata_profile.names import FileHints
from pocs.sqlite_capture.capture import CaptureError, _Deadline

EMPTY_HINTS = FileHints((), (), 0, 0)


@pytest.mark.parametrize(
    ("constant", "bound", "ddl", "rows", "message"),
    [
        ("MAX_TABLES", 0, "CREATE TABLE specimen (uuid)", [], "table"),
        ("MAX_COLUMNS", 0, "CREATE TABLE specimen (uuid)", [], "column"),
        ("MAX_ROWS", 1, "CREATE TABLE specimen (uuid)", [(1,), (2,)], "row"),
        ("MAX_CELLS", 1, "CREATE TABLE specimen (uuid)", [(1,), (2,)], "cell"),
        ("MAX_TEXT_BYTES", 3, "CREATE TABLE specimen (uuid)", [("éé",)], "text"),
    ],
)
def test_rejects_exceeded_bounds(
    monkeypatch: pytest.MonkeyPatch,
    constant: str,
    bound: int,
    ddl: str,
    rows: list[tuple[object, ...]],
    message: str,
) -> None:
    monkeypatch.setattr(profile, constant, bound)
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute(ddl)
        connection.executemany("INSERT INTO specimen VALUES (?)", rows)
        with pytest.raises(profile.ProfileError, match=message):
            profile._inspect(connection, EMPTY_HINTS)


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([], False),
        ([(None,)], False),
        ([("",)], False),
        ([(b"",)], False),
        ([("a",), ("a",)], False),
        ([("a",), ("b",)], True),
        ([("a",), (None,)], False),
        ([(1,), (1.0,)], False),
        ([(1,), ("1",), (b"1",)], True),
        ([("a\0b",), ("a\0c",)], True),
    ],
)
def test_observed_uniqueness_requires_all_nonempty_rows(
    rows: list[tuple[object, ...]], expected: bool
) -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute('CREATE TABLE "日本語" ("recordingid" )')
        connection.executemany('INSERT INTO "日本語" VALUES (?)', rows)
        result = profile._inspect(connection, EMPTY_HINTS)
    assert result.id_candidates[0].unique_nonempty_observed is expected


def test_exact_text_byte_boundary_and_no_unicode_normalization() -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute('CREATE TABLE specimen ("file""path")')
        connection.executemany(
            "INSERT INTO specimen VALUES (?)",
            [("é.m4a",), ("e\u0301.m4a",), ("É.m4a",), ("x" * 4096,)],
        )
        result = profile._inspect(connection, FileHints(("é.m4a",), (), 1, 0))
    assert result.filename_matches["audio_basename_cells"] == 1
    assert result.filename_matches["audio_basename_file_candidates"] == 1


def test_virtual_and_shadow_tables_are_excluded() -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute("CREATE VIRTUAL TABLE private_virtual USING fts5(uuid)")
        connection.execute("INSERT INTO private_virtual VALUES ('private-sentinel')")
        connection.execute("CREATE TABLE specimen (uuid)")
        result = profile._inspect(connection, EMPTY_HINTS)
    assert result.tables_profiled == result.columns_profiled == 1
    assert result.id_candidates[0].rows == 0
    assert "private" not in repr(result)


def test_sqlite_query_timeout_is_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "private.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE specimen (uuid)")
        connection.executemany("INSERT INTO specimen VALUES (?)", [(1,)] * 2000)
        connection.commit()
    monkeypatch.setattr(_Deadline, "query", lambda _self: 1)
    with pytest.raises(
        profile.ProfileError, match="Isolated metadata profiling failed"
    ):
        profile.profile_database(path, EMPTY_HINTS)


def test_backup_timeout_diagnostic_is_fixed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "private.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE specimen (uuid)")
        connection.commit()

    def expired(_self: object, _status: int, _remaining: int, _total: int) -> None:
        raise CaptureError("Isolated inspection timed out")

    monkeypatch.setattr(_Deadline, "backup", expired)
    with pytest.raises(
        profile.ProfileError, match="Isolated metadata profiling failed"
    ):
        profile.profile_database(path, EMPTY_HINTS)


def test_nonhint_columns_are_typed_without_reading_text_values() -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute("CREATE TABLE specimen (opaque)")
        connection.execute("INSERT INTO specimen VALUES (?)", ("x" * 4097,))
        result = profile._inspect(connection, EMPTY_HINTS)
    assert result.cell_types["text"] == 1
    assert result.filename_reference_columns == 0
    assert result.id_candidates == ()
