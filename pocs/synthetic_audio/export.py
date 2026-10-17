"""Raw export for an explicitly designated synthetic recording only."""

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 64 * 1024 * 1024


class ExportError(Exception):
    """Fixed diagnostic without private paths or content."""


@dataclass(frozen=True)
class ExportEvidence:
    size_bytes: int
    sha256: str
    readback_verified: bool


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read(descriptor: int) -> bytes:
    data = bytearray()
    while chunk := os.read(descriptor, min(65_536, MAX_BYTES + 1 - len(data))):
        data.extend(chunk)
        if len(data) > MAX_BYTES:
            raise ExportError("Synthetic audio byte limit exceeded")
    return bytes(data)


def export_audio(source: Path, destination: Path) -> ExportEvidence:
    """Copy unchanged bytes and verify destination readback.

    The caller must select the designated synthetic recording, never arbitrary
    private audio. Source parents are operator-trusted. Equal observations do
    not establish a DB/audio snapshot. Destination creation is exclusive with
    mode 0600; an error after creation can leave an incomplete destination.
    """
    try:
        before = source.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise ExportError("Synthetic audio must be a regular file")
        if before.st_size > MAX_BYTES:
            raise ExportError("Synthetic audio byte limit exceeded")
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or _identity(before) != _identity(
                opened
            ):
                raise ExportError("Synthetic source changed")
            first = _read(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            second = _read(descriptor)
            after = os.fstat(descriptor)
            current = source.stat(follow_symlinks=False)
            if (
                first != second
                or len(first) != opened.st_size
                or _identity(opened) != _identity(after)
                or _identity(opened) != _identity(current)
            ):
                raise ExportError("Synthetic source changed")
        finally:
            os.close(descriptor)
        digest = hashlib.sha256(first).hexdigest()
        output = os.open(destination, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(output, "w+b") as stream:
            stream.write(first)
            stream.flush()
            os.fsync(stream.fileno())
            stream.seek(0)
            readback = stream.read(MAX_BYTES + 1)
        if (
            len(readback) != len(first)
            or hashlib.sha256(readback).hexdigest() != digest
        ):
            raise ExportError("Synthetic export readback failed")
        return ExportEvidence(len(first), digest, True)
    except OSError:
        raise ExportError("Synthetic audio export failed") from None
