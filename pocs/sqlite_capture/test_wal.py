"""Synthetic WAL fixtures plus genuine SQLite-generated checksum evidence."""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

import pytest

from pocs.sqlite_capture.wal import WalError, validate_wal


def _sum(
    data: bytes, order: Literal["little", "big"], state: bytes = bytes(8)
) -> bytes:
    a, b = int.from_bytes(state[:4], "big"), int.from_bytes(state[4:], "big")
    words = [int.from_bytes(data[i : i + 4], order) for i in range(0, len(data), 4)]
    for x, y in zip(words[::2], words[1::2], strict=True):
        a = (a + x + b) % 2**32
        b = (b + y + a) % 2**32
    return a.to_bytes(4, "big") + b.to_bytes(4, "big")


def _main(size: int = 512) -> bytes:
    return (
        b"SQLite format 3\0"
        + (1 if size == 65536 else size).to_bytes(2, "big")
        + bytes(size - 18)
    )


def _wal(
    order: Literal["little", "big"] = "little",
    size: int = 512,
    page: int = 1,
    commit: int = 1,
) -> bytes:
    magic = 0x377F0682 if order == "little" else 0x377F0683
    header = b"".join(v.to_bytes(4, "big") for v in (magic, 3007000, size, 0, 42, 77))
    checksum = _sum(header, order)
    prefix = page.to_bytes(4, "big") + commit.to_bytes(4, "big")
    data = bytes(size)
    return (
        header
        + checksum
        + prefix
        + header[16:24]
        + _sum(prefix + data, order, checksum)
        + data
    )


@pytest.mark.parametrize("order", ["little", "big"])
@pytest.mark.parametrize("size", [512, 65536])
def test_valid_synthetic(order: Literal["little", "big"], size: int) -> None:
    wal = _wal(order, size)
    validate_wal(_main(size), wal)
    validate_wal(_main(size), wal[:32])
    validate_wal(_main(size), b"")


@pytest.mark.parametrize(
    "main",
    [
        b"",
        bytes(512),
        _main()[:100],
        _main()[:16] + b"\0\0" + bytes(494),
        _main()[:16] + b"\0\x03" + bytes(494),
    ],
)
def test_bad_main(main: bytes) -> None:
    with pytest.raises(WalError):
        validate_wal(main, b"")


@pytest.mark.parametrize("offset", [0, 4, 8, 24, 28, 40, 48, 52, 56])
def test_corrupt_wal(offset: int) -> None:
    damaged = bytearray(_wal())
    damaged[offset] ^= 1
    with pytest.raises(WalError):
        validate_wal(_main(), bytes(damaged))


@pytest.mark.parametrize(
    "wal",
    [
        b"x",
        _wal()[:-1],
        _wal(page=0),
        _wal(page=0xFFFFFFFF),
        _wal(commit=0xFFFFFFFF),
        _wal(commit=0),
    ],
)
def test_incomplete_or_unsupported_wal(wal: bytes) -> None:
    with pytest.raises(WalError):
        validate_wal(_main(), wal)


def test_real_sqlite_multitransaction_wal(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        connection.commit()
        connection.execute("INSERT INTO sample(value) VALUES ('synthetic')")
        connection.commit()
        validate_wal(path.read_bytes(), Path(str(path) + "-wal").read_bytes())
