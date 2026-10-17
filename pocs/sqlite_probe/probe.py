"""Schema evidence only; not a validated Voice Memos source adapter."""

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from time import monotonic


class ProbeError(Exception):
    """Sanitized error safe for terminal output."""


@dataclass(frozen=True)
class SchemaInventory:
    schema_sha256: str
    schema_objects: int


class _Deadline:
    def __init__(self) -> None:
        self.expires = monotonic() + 5

    def check(self, _status: int, _remaining: int, _total: int) -> None:
        if monotonic() >= self.expires:
            raise ProbeError("SQLite snapshot timed out")


def probe_database(path: Path) -> SchemaInventory:
    """Read committed WAL state into memory without retaining rows on disk.

    SQLite mode=ro prevents DB writes, but SQLite may create/update WAL shared
    memory files. This does not establish audio/metadata snapshot consistency.
    """
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        with (
            closing(sqlite3.connect(uri, uri=True, timeout=1)) as source,
            closing(sqlite3.connect(":memory:")) as snapshot,
        ):
            source.backup(snapshot, pages=128, progress=_Deadline().check, sleep=0.01)
            rows = snapshot.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_schema "
                "ORDER BY type, name, tbl_name, sql"
            ).fetchall()
            if not rows:
                raise ProbeError("No schema objects; source remains unknown")
            encoded = json.dumps(rows, ensure_ascii=True, separators=(",", ":"))
            return SchemaInventory(
                schema_sha256=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                schema_objects=len(rows),
            )
    except sqlite3.Error, OSError, ValueError:
        raise ProbeError("SQLite probe failed") from None
