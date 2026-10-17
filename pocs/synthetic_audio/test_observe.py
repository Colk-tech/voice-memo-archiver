"""Synthetic-only row selection and comparison tests."""

import sqlite3
from contextlib import closing

import pytest

from pocs.synthetic_audio import observe

PREFIX = "VMA-Phase0-synthetic_%'"


def _setup(connection: sqlite3.Connection) -> None:
    connection.execute('CREATE TABLE "quoted""table" (uuid, filepath, title, extra)')
    connection.execute("CREATE TABLE ignored (title)")
    connection.execute("CREATE TABLE only_id (uuid)")
    connection.execute("CREATE TABLE only_path (filepath)")
    connection.execute(
        'INSERT INTO "quoted""table" VALUES (?,?,?,?)',
        ("stable", "/synthetic/file.m4a", PREFIX + "title", b"\x00\xff"),
    )


def test_selection_and_comparison() -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        _setup(connection)
        before = observe.find_synthetic(connection, PREFIX)
        assert before is not None
        assert before.id_values == (b"tstable",)
        assert before.path_values == ("/synthetic/file.m4a",)
        assert before.values[-1] == b"b\x00\xff"
        assert "stable" not in repr(before)
        assert all(observe.compare_states(before, before).values())
        connection.execute('UPDATE "quoted""table" SET title=?', (PREFIX + "renamed",))
        after = observe.find_synthetic(connection, PREFIX)
        assert after is not None
        assert observe.compare_states(before, after) == {
            "id_hints_unchanged": True,
            "raw_cells_unchanged": False,
            "path_hints_unchanged": True,
        }
        assert observe.find_synthetic(connection, "VMA-Phase0-SYNTHETIC_%'") is None


@pytest.mark.parametrize("prefix", ["", "wrong", "VMA-Phase0-"])
def test_invalid_prefix(prefix: str) -> None:
    with (
        closing(sqlite3.connect(":memory:")) as connection,
        pytest.raises(observe.ObservationError, match="^Synthetic observation failed$"),
    ):
        observe.find_synthetic(connection, prefix)


@pytest.mark.parametrize("other_table", [False, True])
def test_ambiguous_rows(other_table: bool) -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        _setup(connection)
        if other_table:
            connection.execute("CREATE TABLE second (uuid, filepath, title)")
            connection.execute("INSERT INTO second VALUES (1,NULL,?)", (PREFIX,))
        else:
            connection.execute(
                'INSERT INTO "quoted""table" SELECT * FROM "quoted""table"'
            )
        with pytest.raises(observe.ObservationError):
            observe.find_synthetic(connection, PREFIX)


@pytest.mark.parametrize(
    ("name", "limit"),
    [("MAX_TABLES", 3), ("MAX_COLUMNS", 3), ("MAX_ROWS", 0), ("MAX_CELL_BYTES", 1)],
)
def test_bounds(name: str, limit: int, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(observe, name, limit)
    with closing(sqlite3.connect(":memory:")) as connection:
        _setup(connection)
        with pytest.raises(observe.ObservationError):
            observe.find_synthetic(connection, PREFIX)


def test_nontext_paths_and_nulls() -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        _setup(connection)
        connection.execute('UPDATE "quoted""table" SET filepath=NULL,uuid=NULL')
        state = observe.find_synthetic(connection, PREFIX)
        assert state is not None
        assert state.path_values == ()
        assert not observe.compare_states(state, state)["id_hints_unchanged"]
        empty = observe.SyntheticState((), (), (), 0)
        assert not observe.compare_states(empty, empty)["id_hints_unchanged"]
        changed = observe.SyntheticState((), (b"tnew",), ("changed",), 0)
        assert not observe.compare_states(state, changed)["path_hints_unchanged"]


def test_invalid_utf8_path() -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        _setup(connection)
        connection.execute('UPDATE "quoted""table" SET filepath=CAST(X\'FF\' AS TEXT)')
        with pytest.raises(observe.ObservationError):
            observe.find_synthetic(connection, PREFIX)


def test_empty_database_and_sql_error() -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        assert observe.find_synthetic(connection, PREFIX) is None
        connection.set_authorizer(lambda *_: sqlite3.SQLITE_DENY)
        with pytest.raises(observe.ObservationError) as error:
            observe.find_synthetic(connection, PREFIX)
        assert error.value.__suppress_context__


def test_changed_ids() -> None:
    before = observe.SyntheticState((), (b"tbefore",), (), 0)
    after = observe.SyntheticState((), (b"tafter",), (), 0)
    assert not observe.compare_states(before, after)["id_hints_unchanged"]


def test_per_slot_id_changes() -> None:
    before = observe.SyntheticState(
        (), (b"tprivate-one", b"bprivate-two", b"i" + bytes(8), b"r" + bytes(8)), (), 0
    )
    after = observe.SyntheticState(
        (), (b"tprivate-one", b"tchanged", b"i" + bytes(8), b"r" + bytes(8)), (), 0
    )
    result = observe.compare_id_hints(before, after)
    assert result == (
        observe.IdHintChange(0, "text", "text", True),
        observe.IdHintChange(1, "blob", "text", False),
        observe.IdHintChange(2, "integer", "integer", True),
        observe.IdHintChange(3, "real", "real", True),
    )
    assert "private" not in repr(result)


@pytest.mark.parametrize("encoded", [b"n", b"t", b"b"])
def test_identical_absent_ids_are_invalid(encoded: bytes) -> None:
    state = observe.SyntheticState((), (encoded,), (), 0)
    assert not observe.compare_id_hints(state, state)[0].unchanged


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ((), (b"tvalue",)),
        ((b"private",), (b"tvalue",)),
        ((b"tvalue",), (b"private",)),
        ((b"",), (b"",)),
    ],
)
def test_invalid_slot_comparison(
    old: tuple[bytes, ...], new: tuple[bytes, ...]
) -> None:
    before = observe.SyntheticState((), old, (), 0)
    after = observe.SyntheticState((), new, (), 0)
    with pytest.raises(
        observe.ObservationError, match="^Synthetic observation failed$"
    ):
        observe.compare_id_hints(before, after)


def test_no_id_slots() -> None:
    state = observe.SyntheticState((), (), (), 0)
    assert observe.compare_id_hints(state, state) == ()


@pytest.mark.parametrize("encoding", ["UTF-16le", "UTF-16be"])
def test_utf16_database_is_rejected(encoding: str) -> None:
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute(f"PRAGMA encoding='{encoding}'")
        _setup(connection)
        with pytest.raises(
            observe.ObservationError, match="^Synthetic observation failed$"
        ):
            observe.find_synthetic(connection, PREFIX)
