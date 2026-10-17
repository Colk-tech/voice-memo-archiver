"""Fixed synthetic SQL observations, never private Source inputs."""

import sqlite3
from dataclasses import replace

import pytest

from pocs.record_envelope import codec
from pocs.record_trial import trial


def test_sql_to_record_trial() -> None:
    evidence = trial.run_trial()
    assert evidence.databases == 3
    assert evidence.tables == 6
    assert evidence.verified_records == 12
    assert evidence.verified_cells == 84
    assert evidence.generated_columns == 6
    assert evidence.duplicate_pairs_retained == 3
    assert evidence.encodings == ("UTF-8", "UTF-16le", "UTF-16be")
    assert evidence.acquisition_completeness == "UNKNOWN"
    assert evidence.restorability == "UNTESTED"
    assert not evidence.disposal_enabled
    assert "synthetic" not in repr(evidence)
    assert trial.run_trial() == evidence


def test_only_memory_connections_and_query_only_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_connect = sqlite3.connect
    original_inspect = trial._inspect
    opened = []

    def connect(database: str) -> sqlite3.Connection:
        assert database == ":memory:"
        opened.append(database)
        return original_connect(database)

    def inspect(
        connection: sqlite3.Connection,
        encoding: str,
        fixtures: tuple[trial._Fixture, ...],
    ) -> tuple[int, int, int, int]:
        assert connection.execute("PRAGMA trusted_schema").fetchone() == (0,)
        assert connection.execute("PRAGMA temp_store").fetchone() == (2,)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("CREATE TABLE forbidden (value)")
        return original_inspect(connection, encoding, fixtures)

    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(trial, "_inspect", inspect)
    assert trial.run_trial().verified_records == 12
    assert opened == [":memory:"] * 3


@pytest.mark.parametrize("difference", ["sql", "columns", "hidden"])
def test_descriptor_mismatch_is_rejected(
    difference: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_seed = trial._seed

    def seed(
        connection: sqlite3.Connection, encoding: str
    ) -> tuple[trial._Fixture, ...]:
        first, second = original_seed(connection, encoding)
        if difference == "sql":
            first = replace(first, sql=first.sql + " unexpected")
        elif difference == "columns":
            first = replace(first, columns=first.columns[::-1])
        else:
            first = replace(first, hidden=(0,) * len(first.hidden))
        return first, second

    monkeypatch.setattr(trial, "_seed", seed)
    with pytest.raises(trial.TrialError, match="^Synthetic SQL record trial failed$"):
        trial.run_trial()


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE unexpected (value)",
        'DELETE FROM "synthetic""record" WHERE rowid=1',
        "INSERT INTO without_rowid VALUES ('third',NULL,NULL)",
        'UPDATE "synthetic""record" SET nullable=1 WHERE rowid=1',
    ],
)
def test_schema_row_omission_duplication_and_value_mismatches_fail(
    statement: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_seed = trial._seed

    def seed(
        connection: sqlite3.Connection, encoding: str
    ) -> tuple[trial._Fixture, ...]:
        fixtures = original_seed(connection, encoding)
        connection.execute(statement)
        connection.commit()
        return fixtures

    monkeypatch.setattr(trial, "_seed", seed)
    with pytest.raises(trial.TrialError) as error:
        trial.run_trial()
    assert str(error.value) == "Synthetic SQL record trial failed"
    assert error.value.__suppress_context__


def test_wrong_encoding_is_not_reported_as_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_inspect = trial._inspect

    def inspect(
        connection: sqlite3.Connection,
        _encoding: str,
        fixtures: tuple[trial._Fixture, ...],
    ) -> tuple[int, int, int, int]:
        return original_inspect(connection, "UTF-32", fixtures)

    monkeypatch.setattr(trial, "_inspect", inspect)
    with pytest.raises(trial.TrialError):
        trial.run_trial()


def test_value_encoder_mismatch_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trial, "encode_value", lambda _kind, _value: b"n")
    with pytest.raises(trial.TrialError):
        trial.run_trial()


def test_decoded_record_mismatch_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    original_decode = codec.decode_record

    def decode(payload: bytes) -> codec.Record:
        return replace(original_decode(payload), row_slot=99)

    monkeypatch.setattr(codec, "decode_record", decode)
    with pytest.raises(trial.TrialError):
        trial.run_trial()


def test_reencoded_bytes_mismatch_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    original_encode = codec.encode_record
    calls = 0

    def encode(record: codec.Record) -> bytes:
        nonlocal calls
        calls += 1
        payload = original_encode(record)
        return payload if calls == 1 else payload + b"unexpected"

    monkeypatch.setattr(codec, "encode_record", encode)
    with pytest.raises(trial.TrialError):
        trial.run_trial()
    assert calls == 2


def test_sqlite_failure_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    def connect(_database: str) -> sqlite3.Connection:
        raise sqlite3.OperationalError("private-sentinel")

    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(trial.TrialError) as error:
        trial.run_trial()
    assert str(error.value) == "Synthetic SQL record trial failed"
    assert error.value.__suppress_context__
