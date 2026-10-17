"""Observe explicitly marked synthetic rows in a protected memory copy."""

import sqlite3
from dataclasses import dataclass

from pocs.raw_metadata.values import ValueCodecError, encode_value

MAX_TABLES = 64
MAX_COLUMNS = 512
MAX_ROWS = 10_000
MAX_CELL_BYTES = 1024 * 1024
MAX_SCHEMA_BYTES = 1024 * 1024


class ObservationError(Exception):
    """Sanitized failure without private values or identifiers."""


@dataclass(frozen=True, repr=False)
class ComparisonContext:
    table_name: str
    column_names: tuple[str, ...]
    table_sql: bytes
    selection_prefix: str


@dataclass(frozen=True, repr=False)
class SyntheticState:
    values: tuple[bytes, ...]
    id_values: tuple[bytes, ...]
    path_values: tuple[str, ...]
    table_slot: int
    context: ComparisonContext | None = None


@dataclass(frozen=True)
class IdHintChange:
    slot: int
    before_storage_class: str
    after_storage_class: str
    unchanged: bool


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _find(connection: sqlite3.Connection, prefix: str) -> SyntheticState | None:
    if not prefix.startswith("VMA-Phase0-") or len(prefix) <= len("VMA-Phase0-"):
        raise ValueError
    if connection.execute("PRAGMA encoding").fetchone()[0] != "UTF-8":
        raise ValueError
    tables = connection.execute(
        "SELECT name FROM pragma_table_list WHERE schema='main' AND type='table' "
        "AND name NOT IN ('sqlite_schema','sqlite_temp_schema') ORDER BY name LIMIT ?",
        (MAX_TABLES + 1,),
    ).fetchall()
    if len(tables) > MAX_TABLES:
        raise ValueError
    result = None
    for table_slot, (table,) in enumerate(tables):
        columns = connection.execute(
            "SELECT name FROM pragma_table_xinfo(?) ORDER BY cid LIMIT ?",
            (table, MAX_COLUMNS + 1),
        ).fetchall()
        if len(columns) > MAX_COLUMNS:
            raise ValueError
        names = [name for (name,) in columns]
        ids = [
            i
            for i, name in enumerate(names)
            if any(hint in name.lower() for hint in ("uuid", "uniqueid", "recordingid"))
        ]
        paths = [
            i
            for i, name in enumerate(names)
            if any(hint in name.lower() for hint in ("path", "filename", "url"))
        ]
        if not ids or not paths:
            continue
        source = _quote(table)
        rows: int = connection.execute(f"SELECT count(*) FROM {source}").fetchone()[0]
        if rows > MAX_ROWS:
            raise ValueError
        conditions = []
        expressions = []
        for name in names:
            field = _quote(name)
            longest: int = connection.execute(
                f"SELECT coalesce(max(length(CAST({field} AS BLOB))),0) "
                f"FROM {source} WHERE typeof({field}) IN ('text','blob')"
            ).fetchone()[0]
            if longest > MAX_CELL_BYTES:
                raise ValueError
            conditions.append(
                f"(typeof({field})='text' AND substr({field},1,?) COLLATE BINARY = ?)"
            )
            expressions.append(
                f"typeof({field}),CASE WHEN typeof({field})='text' "
                f"THEN CAST({field} AS BLOB) ELSE {field} END"
            )
        parameters = tuple(value for _ in names for value in (len(prefix), prefix))
        query = f"SELECT {','.join(expressions)} FROM {source} WHERE "
        for row in connection.execute(query + " OR ".join(conditions), parameters):
            if result is not None:
                raise ValueError
            values = tuple(
                encode_value(row[i], row[i + 1]) for i in range(0, len(row), 2)
            )
            path_values = tuple(
                values[i][1:].decode("utf-8", errors="strict")
                for i in paths
                if values[i][:1] == b"t"
            )
            # Bound the schema bytes in SQL before returning them to Python.
            (table_sql,) = connection.execute(
                "SELECT CASE WHEN length(CAST(sql AS BLOB)) <= ? "
                "THEN CAST(sql AS BLOB) END FROM main.sqlite_schema "
                "WHERE type='table' AND name=?",
                (MAX_SCHEMA_BYTES, table),
            ).fetchone()
            if not isinstance(table_sql, bytes):
                raise ValueError
            result = SyntheticState(
                values,
                tuple(values[i] for i in ids),
                path_values,
                table_slot,
                ComparisonContext(table, tuple(names), table_sql, prefix),
            )
    return result


def find_synthetic(
    connection: sqlite3.Connection, prefix: str
) -> SyntheticState | None:
    """Caller supplies protected memory DB with query-only flags and deadline.

    SQL observations are not physical records; slots are observation-local.
    Returned private state must never be printed, serialized or committed.
    Only UTF-8 databases are accepted because path TEXT is decoded as UTF-8.
    """
    try:
        return _find(connection, prefix)
    except sqlite3.Error, ValueError, ValueCodecError:
        raise ObservationError("Synthetic observation failed") from None


def _require_comparable(before: SyntheticState, after: SyntheticState) -> None:
    if before.context is None or before.context != after.context:
        raise ObservationError("Synthetic observation failed")


def compare_states(before: SyntheticState, after: SyntheticState) -> dict[str, bool]:
    """Compare matching layouts/prefixes from the caller's same approved Source.

    A matching context is not proof of native identity or source/account
    correspondence. Local table slots may change between observations.
    """
    _require_comparable(before, after)
    valid_ids = bool(before.id_values) and all(
        value not in (b"n", b"t", b"b") for value in before.id_values
    )
    return {
        "id_hints_unchanged": valid_ids and before.id_values == after.id_values,
        "raw_cells_unchanged": before.values == after.values,
        "path_hints_unchanged": before.path_values == after.path_values,
    }


def compare_id_hints(
    before: SyntheticState, after: SyntheticState
) -> tuple[IdHintChange, ...]:
    """Compare observation-local ID positions without returning private bytes."""
    _require_comparable(before, after)
    types = {b"n": "null", b"i": "integer", b"r": "real", b"t": "text", b"b": "blob"}
    if len(before.id_values) != len(after.id_values):
        raise ObservationError("Synthetic observation failed")
    changes = []
    for slot, (old, new) in enumerate(
        zip(before.id_values, after.id_values, strict=True)
    ):
        old_type, new_type = types.get(old[:1]), types.get(new[:1])
        if old_type is None or new_type is None:
            raise ObservationError("Synthetic observation failed")
        changes.append(
            IdHintChange(
                slot,
                old_type,
                new_type,
                old not in (b"n", b"t", b"b") and old == new,
            )
        )
    return tuple(changes)
