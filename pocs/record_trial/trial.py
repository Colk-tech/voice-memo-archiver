"""Observe only self-created synthetic SQLite databases, entirely in memory."""

import sqlite3
import struct
from contextlib import closing
from dataclasses import dataclass

from pocs.raw_metadata.values import encode_value
from pocs.record_envelope import codec

ENCODINGS = ("UTF-8", "UTF-16le", "UTF-16be")
TEXT = "合成\x00e\u0301"
DUPLICATE_SQL = (
    'CREATE TABLE "synthetic""record" ('
    "nullable, minimum INTEGER, maximum INTEGER, real_value REAL, "
    "text_value TEXT, empty_text TEXT, opaque BLOB, empty_blob BLOB, "
    '"unknown""field" "FUTURE TYPE", '
    "computed INTEGER GENERATED ALWAYS AS (minimum+1) VIRTUAL, "
    "stored TEXT GENERATED ALWAYS AS (text_value||'!') STORED)"
)
KEYED_SQL = (
    "CREATE TABLE without_rowid (key TEXT PRIMARY KEY, value BLOB, unknown) "
    "WITHOUT ROWID"
)


class TrialError(Exception):
    """Fixed diagnostic; no schema or values are returned on failure."""


@dataclass(frozen=True)
class TrialEvidence:
    databases: int
    tables: int
    verified_records: int
    verified_cells: int
    generated_columns: int
    duplicate_pairs_retained: int
    encodings: tuple[str, ...]
    sqlite_version: str
    acquisition_completeness: str = "UNKNOWN"
    restorability: str = "UNTESTED"
    disposal_enabled: bool = False


@dataclass(frozen=True, repr=False)
class _Fixture:
    name: str
    sql: str
    order_by: str
    columns: tuple[codec.Column, ...]
    hidden: tuple[int, ...]
    expected_rows: tuple[tuple[bytes, ...], ...]


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _seed(connection: sqlite3.Connection, encoding: str) -> tuple[_Fixture, ...]:
    # All SQL and inserted data are fixed synthetic inputs, not caller data.
    connection.execute(f"PRAGMA encoding='{encoding}'")
    connection.execute(DUPLICATE_SQL)
    connection.execute(KEYED_SQL)
    connection.executemany(
        'INSERT INTO "synthetic""record" VALUES (?,?,?,?,?,?,?,?,?)',
        [(None, -(2**63), 2**63 - 1, 1.5, TEXT, "", b"\x00\xff", b"", "future")] * 2,
    )
    connection.executemany(
        "INSERT INTO without_rowid VALUES (?,?,?)",
        [("second", b"\x80\x00", None), ("first", b"", 123)],
    )
    connection.commit()
    # Expected frames are independent of SQL extraction and encode_value().
    expected = (
        b"n",
        b"i\x80" + bytes(7),
        b"i\x7f" + b"\xff" * 7,
        b"r" + struct.pack(">d", 1.5),
        b"t" + TEXT.encode(encoding),
        b"t",
        b"b\x00\xff",
        b"b",
        b"t" + "future".encode(encoding),
        b"i" + (-(2**63) + 1).to_bytes(8, "big", signed=True),
        b"t" + (TEXT + "!").encode(encoding),
    )
    columns = tuple(
        codec.Column(name, declared)
        for name, declared in (
            ("nullable", ""),
            ("minimum", "INTEGER"),
            ("maximum", "INTEGER"),
            ("real_value", "REAL"),
            ("text_value", "TEXT"),
            ("empty_text", "TEXT"),
            ("opaque", "BLOB"),
            ("empty_blob", "BLOB"),
            ('unknown"field', "FUTURE TYPE"),
            ("computed", "INTEGER"),
            ("stored", "TEXT"),
        )
    )
    return (
        _Fixture(
            'synthetic"record',
            DUPLICATE_SQL,
            "rowid",
            columns,
            (0,) * 9 + (2, 3),
            (expected, expected),
        ),
        _Fixture(
            "without_rowid",
            KEYED_SQL,
            '"key" COLLATE BINARY',
            (
                codec.Column("key", "TEXT"),
                codec.Column("value", "BLOB"),
                codec.Column("unknown", ""),
            ),
            (0, 0, 0),
            (
                (
                    b"t" + "first".encode(encoding),
                    b"b",
                    b"i" + (123).to_bytes(8, "big", signed=True),
                ),
                (b"t" + "second".encode(encoding), b"b\x80\x00", b"n"),
            ),
        ),
    )


def _inspect(
    connection: sqlite3.Connection, encoding: str, fixtures: tuple[_Fixture, ...]
) -> tuple[int, int, int, int]:
    actual_encoding = connection.execute("PRAGMA encoding").fetchone()[0]
    tables = connection.execute(
        "SELECT name FROM pragma_table_list WHERE schema='main' AND type='table' "
        "AND name != 'sqlite_schema' ORDER BY name COLLATE BINARY"
    ).fetchall()
    if actual_encoding != encoding or tables != [(f.name,) for f in fixtures]:
        raise ValueError
    records = cells = generated = duplicate_pairs = 0
    for table_slot, fixture in enumerate(fixtures):
        (sql,) = connection.execute(
            "SELECT sql FROM main.sqlite_schema WHERE type='table' AND name=?",
            (fixture.name,),
        ).fetchone()
        descriptors = connection.execute(
            "SELECT name,type,hidden FROM pragma_table_xinfo(?) ORDER BY cid",
            (fixture.name,),
        ).fetchall()
        columns = tuple(codec.Column(name, kind) for name, kind, _ in descriptors)
        hidden = tuple(flag for _, _, flag in descriptors)
        if sql != fixture.sql or columns != fixture.columns or hidden != fixture.hidden:
            raise ValueError
        generated += sum(flag in (2, 3) for flag in hidden)
        expressions = []
        for column in columns:
            field = _quote(column.name)
            expressions.append(
                f"typeof({field}),CASE WHEN typeof({field})='text' "
                f"THEN CAST({field} AS BLOB) ELSE {field} END"
            )
        rows = connection.execute(
            f"SELECT {','.join(expressions)} FROM {_quote(fixture.name)} "
            f"ORDER BY {fixture.order_by}"
        ).fetchall()
        observed = []
        for row_slot, (row, expected_values) in enumerate(
            zip(rows, fixture.expected_rows, strict=True)
        ):
            values = tuple(
                encode_value(row[index], row[index + 1])
                for index in range(0, len(row), 2)
            )
            record = codec.Record(
                b"synthetic-sql-" + encoding.encode("ascii"),
                table_slot,
                row_slot,
                actual_encoding,
                fixture.name,
                sql,
                columns,
                values,
            )
            expected = codec.Record(
                b"synthetic-sql-" + encoding.encode("ascii"),
                table_slot,
                row_slot,
                encoding,
                fixture.name,
                fixture.sql,
                fixture.columns,
                expected_values,
            )
            if record != expected:
                raise ValueError
            payload = codec.encode_record(record)
            restored = codec.decode_record(payload)
            if restored != expected or codec.encode_record(restored) != payload:
                raise ValueError
            observed.append(restored.values)
            records += 1
            cells += len(values)
        if len(observed) == 2 and observed[0] == observed[1]:
            duplicate_pairs += 1
    return records, cells, generated, duplicate_pairs


def run_trial() -> TrialEvidence:
    """Generate all inputs; expose no path, connection or external data option.

    Read only after seeding each database. All inputs are fixed and small,
    not arbitrary schemas: no general reader, resource guard or capture proof.
    """
    try:
        records = cells = generated = duplicate_pairs = 0
        for encoding in ENCODINGS:
            with closing(sqlite3.connect(":memory:")) as connection:
                fixtures = _seed(connection, encoding)
                connection.execute("PRAGMA trusted_schema=OFF")
                connection.execute("PRAGMA temp_store=MEMORY")
                connection.execute("PRAGMA query_only=ON")
                counts = _inspect(connection, encoding, fixtures)
                records += counts[0]
                cells += counts[1]
                generated += counts[2]
                duplicate_pairs += counts[3]
        return TrialEvidence(
            len(ENCODINGS),
            len(ENCODINGS) * 2,
            records,
            cells,
            generated,
            duplicate_pairs,
            ENCODINGS,
            sqlite3.sqlite_version,
        )
    except sqlite3.Error, ValueError:
        raise TrialError("Synthetic SQL record trial failed") from None
