"""Verify typed SQL observations in memory without emitting private values."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from pocs.raw_metadata.values import ValueCodecError, decode_value, encode_value
from pocs.sqlite_capture.capture import CaptureError, _Deadline

MAX_TABLES = 64
MAX_COLUMNS = 512
MAX_ROWS = 10_000
MAX_CELLS = 1_000_000
MAX_CELL_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
TYPES = ("null", "integer", "real", "text", "blob")


class RoundtripError(Exception):
    """Fixed diagnostic without names, values or SQLite error details."""


@dataclass(frozen=True)
class RoundtripEvidence:
    cell_types: dict[str, int]
    total_cells: int
    verified_cells: int
    sqlite_text_encoding: str
    roundtrip_verified: bool = True
    acquisition_completeness: str = "UNKNOWN"
    disposal_enabled: bool = False


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _inspect(connection: sqlite3.Connection, deadline: _Deadline) -> RoundtripEvidence:
    encoding: str = connection.execute("PRAGMA encoding").fetchone()[0]
    if encoding not in ("UTF-8", "UTF-16le", "UTF-16be"):
        raise ValueError
    tables = connection.execute(
        "SELECT name FROM pragma_table_list WHERE schema='main' AND type='table' "
        "AND name NOT IN ('sqlite_schema', 'sqlite_temp_schema') LIMIT ?",
        (MAX_TABLES + 1,),
    ).fetchall()
    if len(tables) > MAX_TABLES:
        raise ValueError
    totals = dict.fromkeys(TYPES, 0)
    total_cells = verified_cells = payload_bytes = 0
    for (table,) in tables:
        deadline.backup(0, 0, 0)
        source = _quote(table)
        columns = connection.execute(
            "SELECT name FROM pragma_table_xinfo(?) LIMIT ?",
            (table, MAX_COLUMNS + 1),
        ).fetchall()
        if len(columns) > MAX_COLUMNS:
            raise ValueError
        rows: int = connection.execute(f"SELECT count(*) FROM {source}").fetchone()[0]
        total_cells += rows * len(columns)
        if rows > MAX_ROWS or total_cells > MAX_CELLS:
            raise ValueError
        for (column,) in columns:
            deadline.backup(0, 0, 0)
            field = _quote(column)
            # Check byte lengths before fetching individual large values.
            longest: int = connection.execute(
                f"SELECT coalesce(max(length(CAST({field} AS BLOB))),0) "
                f"FROM {source} WHERE typeof({field}) IN ('text','blob')"
            ).fetchone()[0]
            if longest > MAX_CELL_BYTES:
                raise ValueError
            for kind, value in connection.execute(
                f"SELECT typeof({field}), CASE WHEN typeof({field})='text' "
                f"THEN CAST({field} AS BLOB) ELSE {field} END FROM {source}"
            ):
                deadline.backup(0, 0, 0)
                encoded = encode_value(kind, value)
                payload_bytes += len(encoded) - 1
                if payload_bytes > MAX_TOTAL_BYTES:
                    raise ValueError
                decoded_kind, decoded_value = decode_value(encoded)
                if encode_value(decoded_kind, decoded_value) != encoded:
                    raise ValueError
                totals[kind] += 1
                verified_cells += 1
    return RoundtripEvidence(totals, total_cells, verified_cells, encoding)


def verify_database(isolated_database: Path) -> RoundtripEvidence:
    """Caller must supply a protected isolated copy, never the live Source.

    Values are SQL observations, not SQLite's physical bytes or original row
    order. No artifact or raw value leaves memory. This verifies the codec,
    not complete acquisition, ID stability or audio/sidecar consistency.
    """
    try:
        deadline = _Deadline()
        with (
            closing(
                sqlite3.connect(
                    isolated_database.as_uri() + "?mode=ro", uri=True, timeout=1
                )
            ) as copy,
            closing(sqlite3.connect(":memory:")) as memory,
        ):
            copy.execute("PRAGMA trusted_schema=OFF")
            copy.execute("PRAGMA temp_store=MEMORY")
            copy.execute("PRAGMA query_only=ON")
            copy.backup(memory, pages=128, progress=deadline.backup, sleep=0.01)
            memory.set_progress_handler(deadline.query, 1000)
            memory.execute("PRAGMA trusted_schema=OFF")
            memory.execute("PRAGMA temp_store=MEMORY")
            memory.execute("PRAGMA query_only=ON")
            return _inspect(memory, deadline)
    except OSError, sqlite3.Error, ValueError, CaptureError, ValueCodecError:
        raise RoundtripError("Isolated typed metadata verification failed") from None
