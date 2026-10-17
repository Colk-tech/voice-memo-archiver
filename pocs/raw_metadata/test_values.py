"""Synthetic values exercise lossless SQL-observation framing."""

import struct

import pytest

from pocs.raw_metadata.values import ValueCodecError, decode_value, encode_value


@pytest.mark.parametrize(
    ("kind", "value", "encoded"),
    [
        ("null", None, b"n"),
        ("integer", -(2**63), b"i\x80" + bytes(7)),
        ("integer", 2**63 - 1, b"i\x7f" + b"\xff" * 7),
        ("integer", 0, b"i" + bytes(8)),
        ("text", b"", b"t"),
        ("text", b"a\x00\xff\xc0\xaf", b"ta\x00\xff\xc0\xaf"),
        ("blob", b"", b"b"),
        ("blob", bytes(range(256)), b"b" + bytes(range(256))),
    ],
)
def test_exact_roundtrip(kind: str, value: object, encoded: bytes) -> None:
    assert encode_value(kind, value) == encoded
    assert decode_value(encoded) == (kind, value)


@pytest.mark.parametrize(
    "bits",
    [
        "0000000000000000",
        "8000000000000000",
        "3ff0000000000000",
        "0000000000000001",
        "7fefffffffffffff",
        "7ff0000000000000",
        "fff0000000000000",
        "7ff8000000000001",
        "fff8000000001234",
        "7ff0000000000001",
    ],
)
def test_real_preserves_ieee_bits(bits: str) -> None:
    raw = bytes.fromhex(bits)
    value = struct.unpack(">d", raw)[0]
    encoded = encode_value("real", value)
    assert encoded == b"r" + raw
    kind, decoded = decode_value(encoded)
    assert kind == "real"
    assert isinstance(decoded, float)
    assert struct.pack(">d", decoded) == raw


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("private-name", b"private-value"),
        ("NULL", None),
        ("null", 0),
        ("integer", True),
        ("integer", 1.0),
        ("integer", -(2**63) - 1),
        ("integer", 2**63),
        ("real", 1),
        ("text", "private-value"),
        ("blob", bytearray(b"private-value")),
    ],
)
def test_invalid_input_is_sanitized(kind: str, value: object) -> None:
    with pytest.raises(ValueCodecError) as error:
        encode_value(kind, value)
    assert str(error.value) == "Invalid typed SQL value"


@pytest.mark.parametrize(
    "payload",
    [b"", b"private-value", b"nx", b"i", b"i" + bytes(9), b"r", b"r" + bytes(9)],
)
def test_malformed_payload_is_sanitized(payload: bytes) -> None:
    with pytest.raises(ValueCodecError) as error:
        decode_value(payload)
    assert str(error.value) == "Invalid typed SQL value"
