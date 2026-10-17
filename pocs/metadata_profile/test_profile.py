"""Profiles use synthetic rows only; private sentinels must never be emitted."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from pocs.metadata_profile.names import FileHints
from pocs.metadata_profile.profile import ProfileError, profile_database


def test_ids_types_and_ambiguous_filename_hints(tmp_path: Path) -> None:
    path = tmp_path / "private.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('CREATE TABLE "private table" (uuid, filepath TEXT)')
        connection.executemany(
            'INSERT INTO "private table" VALUES (?, ?)',
            [
                ("one", "/private/one.m4a"),
                ("one", "two.m4a"),
                (None, None),
                ("", ""),
                (b"", "one.json"),
                (1, "ONE.m4a"),
                (1.0, "unmatched"),
                (b"one", "one"),
            ],
        )
        connection.commit()
    hints = FileHints(("one.m4a", "one.m4a", "two.m4a"), ("one.json",), 3, 1)
    result = profile_database(path, hints)
    assert result.tables_profiled == 1
    assert result.columns_profiled == 2
    assert result.cell_types == {
        "null": 2,
        "text": 10,
        "integer": 1,
        "real": 1,
        "blob": 2,
    }
    candidate = result.id_candidates[0]
    assert candidate.rows == 8
    assert candidate.nonnull == 7
    assert candidate.distinct_nonnull == 5
    assert candidate.empty_text == candidate.empty_blob == 1
    assert not candidate.unique_nonempty_observed
    assert result.filename_matches["audio_basename_cells"] == 2
    assert result.filename_matches["audio_basename_file_candidates"] == 3
    assert result.filename_matches["audio_basename_ambiguous_cells"] == 1
    assert result.filename_matches["sidecar_basename_cells"] == 1
    assert result.filename_matches["audio_stem_cells"] == 3
    assert "private" not in repr(result)
    assert result.acquisition_completeness == "UNKNOWN"
    assert not result.disposal_enabled


def test_empty_tables_and_quoted_identifiers(tmp_path: Path) -> None:
    path = tmp_path / "fixture.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute('CREATE TABLE "select" ("recordingid" TEXT)')
        connection.execute(
            'CREATE TABLE "with""quote" ("uniqueid" TEXT COLLATE NOCASE)'
        )
        connection.execute("INSERT INTO \"with\"\"quote\" VALUES ('a'), ('A')")
        connection.execute('CREATE VIEW private_view AS SELECT * FROM "select"')
        connection.commit()
    result = profile_database(path, FileHints((), (), 0, 0))
    assert len(result.id_candidates) == 2
    assert not result.id_candidates[0].unique_nonempty_observed
    assert result.id_candidates[1].unique_nonempty_observed
    assert result.id_candidates[1].distinct_nonnull == 2


def test_sanitized_error(tmp_path: Path) -> None:
    with pytest.raises(
        ProfileError, match="Isolated metadata profiling failed"
    ) as error:
        profile_database(tmp_path / "private-missing", FileHints((), (), 0, 0))
    assert "private" not in str(error.value)
