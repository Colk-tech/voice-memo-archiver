"""Frame SQL-observed values, not the original SQLite physical encoding.

TEXT is supplied as CAST(value AS BLOB) bytes without Unicode decoding.
The enclosing artifact supplies framing lengths and the codec version.
"""

import struct


class ValueCodecError(ValueError):
    """Reject invalid framing without exposing private input."""


def encode_value(storage_class: str, value: object) -> bytes:
    """Encode one typed SQL observation without normalization."""
    if storage_class == "null" and value is None:
        return b"n"
    if storage_class == "integer" and type(value) is int and -(2**63) <= value < 2**63:
        return b"i" + value.to_bytes(8, "big", signed=True)
    if storage_class == "real" and type(value) is float:
        return b"r" + struct.pack(">d", value)
    if storage_class == "text" and type(value) is bytes:
        return b"t" + value
    if storage_class == "blob" and type(value) is bytes:
        return b"b" + value
    raise ValueCodecError("Invalid typed SQL value")


def decode_value(payload: bytes) -> tuple[str, object]:
    """Decode one frame; the entire remaining body belongs to TEXT/BLOB."""
    tag, body = payload[:1], payload[1:]
    if tag == b"n" and not body:
        return "null", None
    if tag == b"i" and len(body) == 8:
        return "integer", int.from_bytes(body, "big", signed=True)
    if tag == b"r" and len(body) == 8:
        return "real", struct.unpack(">d", body)[0]
    if tag == b"t":
        return "text", body
    if tag == b"b":
        return "blob", body
    raise ValueCodecError("Invalid typed SQL value")
