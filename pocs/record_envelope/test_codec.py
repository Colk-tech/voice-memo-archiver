"""Synthetic-only record envelope experiments; no Source access."""

import struct
from dataclasses import replace

import pytest

from pocs.raw_metadata.values import encode_value
from pocs.record_envelope import codec


def _record(encoding: str = "UTF-8") -> codec.Record:
    frames = (
        b"n",
        b"t",
        b"b",
        b"i\x80" + bytes(7),
        b"i\x7f" + b"\xff" * 7,
        b"r\x80" + bytes(7),
        b"r" + bytes.fromhex("7ff8000000001234"),
        b"t\x00\xff",
        b"b\x00\xff",
        b"t" + "合成".encode(encoding),
    )
    return codec.Record(
        b"synthetic-observation",
        2,
        3,
        encoding,
        'synthetic"table',
        'CREATE TABLE "synthetic" (unknown)',
        tuple(codec.Column(f"column-{i}", "unknown") for i in range(len(frames))),
        frames,
    )


@pytest.mark.parametrize("encoding", ["UTF-8", "UTF-16le", "UTF-16be"])
def test_record_roundtrip(encoding: str) -> None:
    record = _record(encoding)
    payload = codec.encode_record(record)
    restored = codec.decode_record(payload)
    assert restored == record
    assert codec.encode_record(restored) == payload
    assert restored.values[1:3] == (b"t", b"b")
    assert restored.values[6] == b"r" + bytes.fromhex("7ff8000000001234")
    assert b"synthetic" not in repr(record).encode()
    assert "column" not in repr(record.columns[0])


def test_every_truncation_and_trailing_bytes_is_rejected() -> None:
    payload = codec.encode_record(_record())
    for end in range(len(payload)):
        with pytest.raises(codec.EnvelopeError, match="^Invalid record envelope$"):
            codec.decode_record(payload[:end])
    with pytest.raises(codec.EnvelopeError):
        codec.decode_record(payload + b"trailing")


def test_unknown_columns_and_duplicate_values_are_not_deduplicated() -> None:
    record = replace(
        _record(), columns=(codec.Column("unknown", ""),) * 2, values=(b"n", b"n")
    )
    restored = codec.decode_record(codec.encode_record(record))
    assert restored.columns == record.columns
    assert restored.values == record.values


def test_value_codec_is_reused() -> None:
    record = replace(
        _record(),
        columns=(codec.Column("opaque", "BLOB"),),
        values=(encode_value("blob", b"uninterpreted"),),
    )
    assert codec.decode_record(codec.encode_record(record)) == record


def _field(value: bytes) -> bytes:
    return struct.pack(">I", len(value)) + value


def _wire(
    *,
    observation_id: bytes = b"observation",
    encoding: bytes = b"UTF-8",
    provenance: bytes = codec.PROVENANCE,
    table: bytes = b"table",
    column: bytes = b"unknown",
    cell: bytes = b"n",
    count: int = 1,
) -> bytes:
    # Independent minimal wire fixture, including duplicate zero slots.
    return (
        b"VMAR\x00\x00\x00\x01\x00\x00\x00\x01"
        + _field(provenance)
        + _field(observation_id)
        + bytes(8)
        + _field(encoding)
        + _field(table)
        + _field(b"")
        + struct.pack(">I", count)
        + _field(column)
        + _field(b"")
        + _field(cell)
    )


def test_independent_wire_fixture() -> None:
    payload = _wire()
    record = codec.decode_record(payload)
    assert record == codec.Record(
        b"observation",
        0,
        0,
        "UTF-8",
        "table",
        "",
        (codec.Column("unknown", ""),),
        (b"n",),
    )
    assert codec.encode_record(record) == payload


@pytest.mark.parametrize("offset", [0, 4, 8])
def test_unknown_magic_and_versions(offset: int) -> None:
    payload = _wire()
    payload = payload[:offset] + b"\xff" + payload[offset + 1 :]
    with pytest.raises(codec.EnvelopeError, match="^Invalid record envelope$"):
        codec.decode_record(payload)


@pytest.mark.parametrize(
    "payload",
    [
        _wire(observation_id=b""),
        _wire(observation_id=b"x" * 65),
        _wire(encoding=b"UTF-32"),
        _wire(provenance=b"private-sentinel"),
        _wire(table=b"\xffprivate-sentinel"),
        _wire(column=b"\xffprivate-sentinel"),
        _wire(cell=b""),
        _wire(cell=b"invalid-private-sentinel"),
        _wire(cell=b"nx"),
        _wire(cell=b"r"),
        _wire(count=0),
        _wire(count=513),
    ],
)
def test_invalid_wire_is_sanitized(payload: bytes) -> None:
    with pytest.raises(codec.EnvelopeError) as error:
        codec.decode_record(payload)
    assert str(error.value) == "Invalid record envelope"
    assert error.value.__suppress_context__


@pytest.mark.parametrize("slot", [-1, 2**32, True])
@pytest.mark.parametrize("field", ["table_slot", "row_slot"])
def test_invalid_slots(slot: int, field: str) -> None:
    record = _record()
    record = (
        replace(record, table_slot=slot)
        if field == "table_slot"
        else replace(record, row_slot=slot)
    )
    with pytest.raises(codec.EnvelopeError):
        codec.encode_record(record)


def test_maximum_slots_and_observation_id() -> None:
    record = replace(
        _record(), observation_id=b"x" * 64, table_slot=2**32 - 1, row_slot=2**32 - 1
    )
    assert codec.decode_record(codec.encode_record(record)) == record


@pytest.mark.parametrize(
    "record",
    [
        replace(_record(), observation_id=b""),
        replace(_record(), observation_id=b"x" * 65),
        replace(_record(), sqlite_text_encoding="unknown-private-sentinel"),
        replace(_record(), columns=(), values=()),
        replace(
            _record(), columns=(codec.Column("x", ""),) * 513, values=(b"n",) * 513
        ),
        replace(_record(), values=(b"n",)),
        replace(_record(), table_name="private-sentinel\ud800"),
        replace(_record(), values=(b"invalid-private-sentinel",) * 10),
    ],
)
def test_invalid_record_is_sanitized(record: codec.Record) -> None:
    with pytest.raises(codec.EnvelopeError) as error:
        codec.encode_record(record)
    assert str(error.value) == "Invalid record envelope"
    assert error.value.__suppress_context__


def test_maximum_column_count() -> None:
    record = replace(
        _record(), columns=(codec.Column("", ""),) * 512, values=(b"n",) * 512
    )
    assert codec.decode_record(codec.encode_record(record)) == record


@pytest.mark.parametrize("extra", [0, 1])
def test_cell_limit(extra: int) -> None:
    cell = b"b" + bytes(codec.MAX_CELL_BYTES + extra)
    wire = _wire(cell=cell)
    record = replace(_record(), columns=(codec.Column("x", ""),), values=(cell,))
    if extra:
        for operation in (
            lambda: codec.encode_record(record),
            lambda: codec.decode_record(wire),
        ):
            with pytest.raises(codec.EnvelopeError):
                operation()
    else:
        assert codec.decode_record(wire).values == (cell,)
        assert codec.decode_record(codec.encode_record(record)) == record


@pytest.mark.parametrize("text", ["x" * (1024 * 1024 + 1), "界" * (1024 * 1024)])
def test_descriptor_encoding_limits(text: str) -> None:
    with pytest.raises(codec.EnvelopeError):
        codec.encode_record(replace(_record(), table_sql=text))


def test_descriptor_byte_boundary() -> None:
    record = replace(_record(), table_sql="x" * codec.MAX_FIELD_BYTES)
    assert codec.decode_record(codec.encode_record(record)) == record
    with pytest.raises(codec.EnvelopeError):
        codec.decode_record(_wire(table=b"x" * (codec.MAX_FIELD_BYTES + 1)))


def test_aggregate_frame_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    record = _record()
    wire = codec.encode_record(record)
    monkeypatch.setattr(codec, "MAX_FRAME_BYTES", len(wire))
    assert codec.encode_record(record) == wire
    assert codec.decode_record(wire) == record
    monkeypatch.setattr(codec, "MAX_FRAME_BYTES", len(wire) - 1)
    for operation in (
        lambda: codec.encode_record(record),
        lambda: codec.decode_record(wire),
    ):
        with pytest.raises(codec.EnvelopeError):
            operation()


def test_huge_declared_length_is_rejected_without_a_body() -> None:
    with pytest.raises(codec.EnvelopeError):
        codec.decode_record(_wire()[:12] + b"\xff" * 4)


def test_order_and_observation_context_affect_framing() -> None:
    record = _record()
    encoded = codec.encode_record(record)
    alternatives = (
        replace(record, columns=record.columns[::-1], values=record.values[::-1]),
        replace(record, observation_id=b"another-observation"),
        replace(record, row_slot=4),
        replace(record, table_slot=4),
        replace(record, table_name="another"),
        replace(record, table_sql="another"),
    )
    for alternative in alternatives:
        assert codec.encode_record(alternative) != encoded
        assert codec.decode_record(codec.encode_record(alternative)) == alternative


@pytest.mark.parametrize(
    "bits",
    [
        "0000000000000000",
        "8000000000000000",
        "0000000000000001",
        "7fefffffffffffff",
        "7ff0000000000000",
        "fff0000000000000",
        "7ff8000000000001",
        "fff8000000001234",
        "7ff0000000000001",
    ],
)
def test_real_bits_are_retained_without_reencoding(bits: str) -> None:
    frame = b"r" + bytes.fromhex(bits)
    payload = _wire(cell=frame)
    restored = codec.decode_record(payload)
    assert restored.values == (frame,)
    assert codec.encode_record(restored) == payload


def test_unicode_descriptors_are_not_normalized() -> None:
    record = replace(
        _record(),
        table_name="合成-é-e\u0301",
        table_sql="合成 SQL",
        columns=(codec.Column("未知-é-e\u0301", "型"),),
        values=(b"t\xff",),
    )
    restored = codec.decode_record(codec.encode_record(record))
    assert restored == record
    assert restored.table_name.endswith("é-e\u0301")


def test_actual_aggregate_limit() -> None:
    record = replace(
        _record(),
        columns=(codec.Column("x", ""),) * 7,
        values=(b"b" + bytes(codec.MAX_CELL_BYTES),) * 7,
    )
    payload = codec.encode_record(record)
    assert len(payload) < 8 * 1024 * 1024
    assert codec.decode_record(payload) == record
    eighth = replace(
        record,
        columns=record.columns + (codec.Column("x", ""),),
        values=record.values + (record.values[0],),
    )
    with pytest.raises(codec.EnvelopeError):
        codec.encode_record(eighth)
    with pytest.raises(codec.EnvelopeError):
        codec.decode_record(bytes(8 * 1024 * 1024 + 1))
