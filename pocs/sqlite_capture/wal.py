"""Conservative byte-only WAL checks from sqlite.org/fileformat.html#walformat.

Reject even legitimate stale/uncommitted tails rather than silently omit data.
Checksums do not authenticate the DB/WAL pairing or prove an atomic snapshot.
"""

from typing import Literal


class WalError(Exception):
    """Fixed, content-free diagnostic for an unsupported capture."""


def _checksum(
    data: bytes, order: Literal["little", "big"], state: tuple[int, int] = (0, 0)
) -> tuple[int, int]:
    first, second = state
    for offset in range(0, len(data), 8):
        first = (
            first + int.from_bytes(data[offset : offset + 4], order) + second
        ) & 0xFFFFFFFF
        second = (
            second + int.from_bytes(data[offset + 4 : offset + 8], order) + first
        ) & 0xFFFFFFFF
    return first, second


def validate_wal(main: bytes, wal: bytes) -> None:
    """Validate supported DB header and every WAL frame without SQLite or I/O.

    An empty WAL or a checksum-valid header without frames is accepted. Any
    nonempty frame sequence must end in a commit; incomplete and stale tails
    are rejected. Main content still requires isolated SQLite integrity checks.
    """
    if len(main) < 100 or main[:16] != b"SQLite format 3\0":
        raise WalError("Unsupported database header")
    encoded = int.from_bytes(main[16:18], "big")
    page_size = 65536 if encoded == 1 else encoded
    if page_size < 512 or page_size > 65536 or page_size & (page_size - 1):
        raise WalError("Unsupported database page size")
    if len(main) % page_size:
        raise WalError("Incomplete database page")
    if not wal:
        return
    if len(wal) < 32:
        raise WalError("Incomplete WAL header")
    magic = int.from_bytes(wal[:4], "big")
    if magic not in (0x377F0682, 0x377F0683):
        raise WalError("Unsupported WAL magic")
    if int.from_bytes(wal[4:8], "big") != 3007000:
        raise WalError("Unsupported WAL version")
    if int.from_bytes(wal[8:12], "big") != page_size:
        raise WalError("Incompatible WAL page size")
    order: Literal["little", "big"] = "little" if magic == 0x377F0682 else "big"
    state = _checksum(wal[:24], order)
    if state != (int.from_bytes(wal[24:28], "big"), int.from_bytes(wal[28:32], "big")):
        raise WalError("Invalid WAL header checksum")
    frame_size = 24 + page_size
    if (len(wal) - 32) % frame_size:
        raise WalError("Incomplete WAL frame")
    commit = 1
    for offset in range(32, len(wal), frame_size):
        frame = wal[offset : offset + frame_size]
        page = int.from_bytes(frame[:4], "big")
        commit = int.from_bytes(frame[4:8], "big")
        if page == 0 or page == 0xFFFFFFFF or commit == 0xFFFFFFFF:
            raise WalError("Unsupported WAL page number")
        if frame[8:16] != wal[16:24]:
            raise WalError("Invalid WAL frame salt")
        state = _checksum(frame[:8] + frame[24:], order, state)
        if state != (
            int.from_bytes(frame[16:20], "big"),
            int.from_bytes(frame[20:24], "big"),
        ):
            raise WalError("Invalid WAL frame checksum")
    if not commit:
        raise WalError("Uncommitted WAL tail")
