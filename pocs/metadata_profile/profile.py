"""Schema ordinals and fixed aggregate counts; no raw metadata leaves memory."""

import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from pocs.metadata_profile.names import FileHints
from pocs.sqlite_capture.capture import CaptureError, _Deadline

MAX_TABLES = 64
MAX_COLUMNS = 512
MAX_ROWS = 10_000
MAX_CELLS = 1_000_000
MAX_TEXT_BYTES = 4096
TYPES = ("null", "integer", "real", "text", "blob")


class ProfileError(Exception):
    """Fixed diagnostic; input-derived SQLite errors are never exposed."""


@dataclass(frozen=True)
class IdCandidate:
    table_slot: int
    column_slot: int
    rows: int
    nonnull: int
    distinct_nonnull: int
    empty_text: int
    empty_blob: int
    cell_types: dict[str, int]
    unique_nonempty_observed: bool


@dataclass(frozen=True)
class MetadataProfile:
    tables_profiled: int
    columns_profiled: int
    cell_types: dict[str, int]
    id_candidates: tuple[IdCandidate, ...]
    filename_reference_columns: int
    filename_matches: dict[str, int]
    audio_filename_entries: int
    sidecar_filename_entries: int
    acquisition_completeness: str = "UNKNOWN"
    snapshot_consistency: str = "unknown"
    id_stability: str = "unknown"
    disposal_enabled: bool = False


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _matches(values: list[str], hints: FileHints) -> dict[str, int]:
    counts: dict[str, int] = {}
    for kind, names in (("audio", hints.audio), ("sidecar", hints.sidecar)):
        for rule in ("basename", "stem"):
            candidates = Counter(
                name if rule == "basename" else Path(name).stem for name in names
            )
            prefix = f"{kind}_{rule}"
            counts[prefix + "_cells"] = 0
            counts[prefix + "_file_candidates"] = 0
            counts[prefix + "_ambiguous_cells"] = 0
            for value in values:
                # No URL decoding, Unicode normalization or case folding.
                number = candidates[Path(value).name]
                counts[prefix + "_cells"] += int(number > 0)
                counts[prefix + "_file_candidates"] += number
                counts[prefix + "_ambiguous_cells"] += int(number > 1)
    return counts


def _inspect(connection: sqlite3.Connection, hints: FileHints) -> MetadataProfile:
    tables = connection.execute(
        "SELECT name FROM pragma_table_list WHERE schema='main' AND type='table' "
        "AND name NOT IN ('sqlite_schema', 'sqlite_temp_schema') ORDER BY name"
    ).fetchall()
    if len(tables) > MAX_TABLES:
        raise ProfileError("Metadata table bound exceeded")
    totals = dict.fromkeys(TYPES, 0)
    candidates: list[IdCandidate] = []
    matches = _matches([], hints)
    column_count = cells = references = 0
    for table_slot, (table,) in enumerate(tables):
        source = _quote(table)
        columns = connection.execute(
            "SELECT name FROM pragma_table_xinfo(?) ORDER BY cid", (table,)
        ).fetchall()
        if len(columns) > MAX_COLUMNS:
            raise ProfileError("Metadata column bound exceeded")
        rows: int = connection.execute(f"SELECT count(*) FROM {source}").fetchone()[0]
        cells += rows * len(columns)
        if rows > MAX_ROWS or cells > MAX_CELLS:
            raise ProfileError("Metadata row or cell bound exceeded")
        for column_slot, (field,) in enumerate(columns):
            column_count += 1
            key = _quote(field)
            types = dict.fromkeys(TYPES, 0)
            for kind, number in connection.execute(
                f"SELECT typeof({key}), count(*) FROM {source} GROUP BY typeof({key})"
            ):
                types[kind] = number
                totals[kind] += number
            id_hint = any(
                part in field.lower() for part in ("uuid", "uniqueid", "recordingid")
            )
            path_hint = any(
                part in field.lower() for part in ("path", "filename", "url")
            )
            if id_hint:
                nonnull, distinct, empty_text, empty_blob = connection.execute(
                    f"SELECT count({key}), count(DISTINCT {key} COLLATE BINARY), "
                    f"coalesce(sum(typeof({key})='text' "
                    f"AND length(CAST({key} AS BLOB))=0),0), "
                    f"coalesce(sum(typeof({key})='blob' "
                    f"AND length({key})=0),0) FROM {source}"
                ).fetchone()
                candidates.append(
                    IdCandidate(
                        table_slot,
                        column_slot,
                        rows,
                        nonnull,
                        distinct,
                        empty_text,
                        empty_blob,
                        types,
                        rows > 0
                        and rows == nonnull == distinct
                        and empty_text + empty_blob == 0,
                    )
                )
            if id_hint or path_hint:
                references += 1
                longest = connection.execute(
                    f"SELECT coalesce(max(length(CAST({key} AS BLOB))),0) "
                    f"FROM {source} WHERE typeof({key})='text'"
                ).fetchone()[0]
                if longest > MAX_TEXT_BYTES:
                    raise ProfileError("Metadata text bound exceeded")
                values = [
                    row[0]
                    for row in connection.execute(
                        f"SELECT {key} FROM {source} WHERE typeof({key})='text'"
                    )
                ]
                for name, count in _matches(values, hints).items():
                    matches[name] += count
    return MetadataProfile(
        len(tables),
        column_count,
        totals,
        tuple(candidates),
        references,
        matches,
        len(hints.audio),
        len(hints.sidecar),
    )


def profile_database(isolated_database: Path, hints: FileHints) -> MetadataProfile:
    """Caller must supply a protected copy, never a live Source database.

    All SQL aggregation runs in memory with a deadline and fixed bounds.
    Ordinals identify positions in this observation only, not stable identity.
    """
    try:
        with (
            closing(
                sqlite3.connect(
                    isolated_database.as_uri() + "?mode=ro", uri=True, timeout=1
                )
            ) as copy,
            closing(sqlite3.connect(":memory:")) as memory,
        ):
            copy.execute("PRAGMA trusted_schema=OFF")
            deadline = _Deadline()
            copy.backup(memory, pages=128, progress=deadline.backup, sleep=0.01)
            memory.set_progress_handler(deadline.query, 1000)
            memory.execute("PRAGMA trusted_schema=OFF")
            memory.execute("PRAGMA temp_store=MEMORY")
            memory.execute("PRAGMA query_only=ON")
            return _inspect(memory, hints)
    except OSError, sqlite3.Error, ValueError, CaptureError:
        raise ProfileError("Isolated metadata profiling failed") from None
