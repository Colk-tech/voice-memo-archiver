"""Deterministic counterexamples using generated inputs only."""

from pocs.snapshot_trial.trial import run_trial


def test_wal_commit_requires_wal_aware_snapshot() -> None:
    evidence = run_trial()
    assert evidence.main_copy_rows == 0
    assert evidence.immutable_rows == 0
    assert evidence.backup_rows == 1
    assert evidence.backup_excludes_uncommitted
    assert evidence.source_db_unchanged_by_reads
    assert evidence.source_wal_unchanged_by_reads
    assert evidence.sqlite_version


def test_database_backup_does_not_freeze_external_audio() -> None:
    assert not run_trial().external_artifact_matches_snapshot
