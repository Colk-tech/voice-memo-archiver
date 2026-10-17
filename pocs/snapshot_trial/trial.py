"""Create all inputs locally; never accept or discover a source path."""

import hashlib
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory


@dataclass(frozen=True)
class TrialEvidence:
    main_copy_rows: int
    immutable_rows: int
    backup_rows: int
    backup_excludes_uncommitted: bool
    source_db_unchanged_by_reads: bool
    source_wal_unchanged_by_reads: bool
    external_artifact_matches_snapshot: bool
    sqlite_version: str


def run_trial() -> TrialEvidence:
    """Demonstrate WAL omission and a deterministic cross-file revision race.

    Every database and artifact is synthetic and temporary. The artifact bytes
    simulate revisions; they are not an encoded audio recording. Read-only
    SQLite may still touch SHM. This is not a production snapshot algorithm.
    """
    with TemporaryDirectory(prefix="synthetic-snapshot-trial-") as directory:
        root = Path(directory)
        database = root / "synthetic.sqlite"
        artifact = root / "synthetic.audio"
        artifact.write_bytes(b"synthetic revision one")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        with (
            closing(sqlite3.connect(database)) as writer,
            closing(sqlite3.connect(":memory:")) as snapshot,
        ):
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("CREATE TABLE recording (revision INTEGER, digest TEXT)")
            writer.commit()
            writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            writer.execute("INSERT INTO recording VALUES (1, ?)", (digest,))
            writer.commit()
            before_db = database.read_bytes()
            wal = root / "synthetic.sqlite-wal"
            before_wal = wal.read_bytes()

            # The schema is checkpointed, but its committed row exists in WAL.
            main_copy = root / "main-only.sqlite"
            main_copy.write_bytes(before_db)
            with (
                closing(
                    sqlite3.connect(main_copy.as_uri() + "?mode=ro", uri=True)
                ) as copied,
                closing(
                    sqlite3.connect(
                        database.as_uri() + "?mode=ro&immutable=1", uri=True
                    )
                ) as immutable,
                closing(
                    sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
                ) as reader,
            ):
                main_copy_rows = len(
                    copied.execute("SELECT * FROM recording").fetchall()
                )
                immutable_rows = len(
                    immutable.execute("SELECT * FROM recording").fetchall()
                )
                # An open writer transaction is deliberately absent from backup.
                writer.execute("INSERT INTO recording VALUES (99, 'uncommitted')")
                reader.backup(snapshot)
                backup_rows = snapshot.execute("SELECT * FROM recording").fetchall()
                writer.rollback()

            db_unchanged = database.read_bytes() == before_db
            wal_unchanged = wal.read_bytes() == before_wal

            # Schedule an edit after DB backup and before artifact capture.
            # Both states are valid independently; their pair is inconsistent.
            artifact.write_bytes(b"synthetic revision two")
            new_digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            writer.execute("UPDATE recording SET revision=2, digest=?", (new_digest,))
            writer.commit()
            return TrialEvidence(
                main_copy_rows=main_copy_rows,
                immutable_rows=immutable_rows,
                backup_rows=len(backup_rows),
                backup_excludes_uncommitted=backup_rows == [(1, digest)],
                source_db_unchanged_by_reads=db_unchanged,
                source_wal_unchanged_by_reads=wal_unchanged,
                external_artifact_matches_snapshot=backup_rows[0][1] == new_digest,
                sqlite_version=sqlite3.sqlite_version,
            )
