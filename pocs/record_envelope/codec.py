"""In-memory experimental frames, not a production metadata archive.

Only synthetic caller-supplied observations are supported by this PoC.
There is no database, filesystem, network or source-selection API.
"""

import struct
from dataclasses import dataclass

from pocs.raw_metadata.values import decode_value

MAGIC = b"VMAR"
ENVELOPE_VERSION = 1
VALUE_CODEC_VERSION = 1
PROVENANCE = b"caller-supplied-synthetic-sql-observation"
ENCODINGS = ("UTF-8", "UTF-16le", "UTF-16be")
MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_FIELD_BYTES = 1024 * 1024
MAX_CELL_BYTES = 1024 * 1024  # Value body; excludes its one-byte type tag.
MAX_COLUMNS = 512
MAX_OBSERVATION_BYTES = 64
UINT32_MAX = 2**32 - 1


class EnvelopeError(ValueError):
    """Fixed diagnostic without record contents or schema."""


@dataclass(frozen=True, repr=False)
class Column:
    name: str
    declared_type: str


@dataclass(frozen=True, repr=False)
class Record:
    """Synthetic observation; slots are local, never native recording IDs.

    Descriptors are UTF-8 strings without normalization. Value frames retain
    SQL-observed bytes, interpreted using sqlite_text_encoding for TEXT.
    Duplicate/empty descriptors are retained, not validated as a SQL schema.
    Names, SQL and values must not be logged. No completeness is asserted.
    """

    observation_id: bytes
    table_slot: int
    row_slot: int
    sqlite_text_encoding: str
    table_name: str
    table_sql: str
    columns: tuple[Column, ...]
    values: tuple[bytes, ...]


class _Writer:
    def __init__(self) -> None:
        self.data = bytearray()

    def write(self, value: bytes) -> None:
        if len(value) > MAX_FRAME_BYTES - len(self.data):
            raise ValueError
        self.data.extend(value)

    def uint(self, value: int) -> None:
        if type(value) is not int or not 0 <= value <= UINT32_MAX:
            raise ValueError
        self.write(struct.pack(">I", value))

    def field(self, value: bytes, limit: int) -> None:
        if len(value) > limit:
            raise ValueError
        self.uint(len(value))
        self.write(value)

    def text(self, value: str) -> None:
        # Bound codepoints before UTF-8 allocation, then bound encoded bytes.
        if len(value) > MAX_FIELD_BYTES:
            raise ValueError
        self.field(value.encode("utf-8", errors="strict"), MAX_FIELD_BYTES)


class _Reader:
    def __init__(self, payload: bytes) -> None:
        if len(payload) > MAX_FRAME_BYTES:
            raise ValueError
        self.payload = payload
        self.position = 0

    def take(self, size: int) -> bytes:
        if size > len(self.payload) - self.position:
            raise ValueError
        start = self.position
        self.position += size
        return self.payload[start : self.position]

    def uint(self) -> int:
        return int.from_bytes(self.take(4), "big")

    def field(self, limit: int) -> bytes:
        size = self.uint()
        if size > limit:
            raise ValueError
        return self.take(size)

    def text(self) -> str:
        return self.field(MAX_FIELD_BYTES).decode("utf-8", errors="strict")


def _validate_value(frame: bytes) -> None:
    if len(frame) > MAX_CELL_BYTES + 1:
        raise ValueError
    # Validate, but retain the original frame, including IEEE754 bit patterns.
    decode_value(frame)


def _encode(record: Record) -> bytes:
    if not 1 <= len(record.observation_id) <= MAX_OBSERVATION_BYTES:
        raise ValueError
    if record.sqlite_text_encoding not in ENCODINGS:
        raise ValueError
    count = len(record.columns)
    if not 1 <= count <= MAX_COLUMNS or count != len(record.values):
        raise ValueError
    writer = _Writer()
    writer.write(MAGIC)
    writer.uint(ENVELOPE_VERSION)
    writer.uint(VALUE_CODEC_VERSION)
    writer.field(PROVENANCE, MAX_FIELD_BYTES)
    writer.field(record.observation_id, MAX_OBSERVATION_BYTES)
    writer.uint(record.table_slot)
    writer.uint(record.row_slot)
    writer.text(record.sqlite_text_encoding)
    writer.text(record.table_name)
    writer.text(record.table_sql)
    writer.uint(count)
    for column in record.columns:
        writer.text(column.name)
        writer.text(column.declared_type)
    for frame in record.values:
        _validate_value(frame)
        writer.field(frame, MAX_CELL_BYTES + 1)
    return bytes(writer.data)


def encode_record(record: Record) -> bytes:
    """Frame only synthetic inputs in memory; never serialize SyntheticState."""
    try:
        return _encode(record)
    except ValueError:
        raise EnvelopeError("Invalid record envelope") from None


def _decode(payload: bytes) -> Record:
    reader = _Reader(payload)
    if (
        reader.take(len(MAGIC)) != MAGIC
        or reader.uint() != ENVELOPE_VERSION
        or reader.uint() != VALUE_CODEC_VERSION
    ):
        raise ValueError
    if reader.field(MAX_FIELD_BYTES) != PROVENANCE:
        raise ValueError
    observation_id = reader.field(MAX_OBSERVATION_BYTES)
    if not observation_id:
        raise ValueError
    table_slot, row_slot = reader.uint(), reader.uint()
    encoding = reader.text()
    if encoding not in ENCODINGS:
        raise ValueError
    table, sql = reader.text(), reader.text()
    count = reader.uint()
    if not 1 <= count <= MAX_COLUMNS:
        raise ValueError
    columns = tuple(Column(reader.text(), reader.text()) for _ in range(count))
    values = []
    for _ in range(count):
        frame = reader.field(MAX_CELL_BYTES + 1)
        _validate_value(frame)
        values.append(frame)
    if reader.position != len(payload):
        raise ValueError
    return Record(
        observation_id,
        table_slot,
        row_slot,
        encoding,
        table,
        sql,
        columns,
        tuple(values),
    )


def decode_record(payload: bytes) -> Record:
    """Reject malformed frames; this does not authenticate their provenance."""
    try:
        return _decode(payload)
    except ValueError:
        raise EnvelopeError("Invalid record envelope") from None
