"""Bounded, memory-only signature hints for explicitly selected source roots."""

import os
import stat
from pathlib import Path

from pocs.source_layout.layout import category


class SidecarError(Exception):
    """Fixed diagnostic; never includes source information or partial results."""


def classify(data: bytes) -> str:
    """Recognize signatures only, without parsing or claiming valid formats."""
    if data.startswith(b"bplist00"):
        return "binary_plist_candidate"
    prefix = data.lstrip()
    if prefix.startswith((b"<?xml", b"<plist")):
        return "xml_plist_candidate"
    if prefix.startswith((b"{", b"[")):
        return "json_candidate"
    return "other"


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    remaining = limit + 1
    while remaining:
        chunk = os.read(descriptor, min(65_536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) > limit:
        raise SidecarError("Sidecar byte limit exceeded; no report produced")
    return data


def _observe(parent: int, name: str, before: os.stat_result, limit: int) -> bytes:
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
    )
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _identity(before) != _identity(opened):
            raise SidecarError("Source changed; no report produced")
        first = _read(descriptor, limit)
        os.lseek(descriptor, 0, os.SEEK_SET)
        second = _read(descriptor, limit)
        after = os.fstat(descriptor)
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (
            first != second
            or len(first) != opened.st_size
            or _identity(opened) != _identity(after)
            or _identity(opened) != _identity(current)
        ):
            raise SidecarError("Source changed; no report produced")
        return first
    finally:
        os.close(descriptor)


def inspect_sidecars(
    root: Path,
    *,
    entry_limit: int = 10_000,
    max_depth: int = 4,
    file_limit: int = 1_048_576,
    total_limit: int = 8_388_608,
) -> dict[str, int]:
    """Return fixed aggregates, never content, names, sizes or hashes.

    Only fixed sidecar suffix candidates are opened. Parent components of root
    are operator-trusted. Equal repeated reads do not establish an atomic source
    snapshot, materialization, association, completeness or restoration safety.
    """
    if (
        not 1 <= entry_limit <= 10_000
        or not 0 <= max_depth <= 4
        or not 1 <= file_limit <= 1_048_576
        or not 1 <= total_limit <= 8_388_608
    ):
        raise SidecarError("Invalid observation bounds")
    counts = dict.fromkeys(
        (
            "files_observed",
            "equal_repeated_reads",
            "binary_plist_candidate",
            "xml_plist_candidate",
            "json_candidate",
            "other",
        ),
        0,
    )
    entries_seen = 0
    bytes_seen = 0

    def scan(parent: int, depth: int) -> None:
        nonlocal entries_seen, bytes_seen
        with os.scandir(parent) as entries:
            for entry in entries:
                entries_seen += 1
                if entries_seen > entry_limit:
                    raise SidecarError("Entry limit exceeded; no report produced")
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    if depth == max_depth:
                        raise SidecarError("Depth limit exceeded; no report produced")
                    child = os.open(
                        entry.name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=parent,
                    )
                    try:
                        if _identity(info) != _identity(os.fstat(child)):
                            raise SidecarError("Source changed; no report produced")
                        scan(child, depth + 1)
                    finally:
                        os.close(child)
                elif (
                    stat.S_ISREG(info.st_mode)
                    and category(entry.name) == "sidecar_candidate"
                ):
                    if (
                        info.st_size > file_limit
                        or bytes_seen + info.st_size > total_limit
                    ):
                        raise SidecarError(
                            "Sidecar byte limit exceeded; no report produced"
                        )
                    data = _observe(parent, entry.name, info, file_limit)
                    bytes_seen += len(data)
                    counts["files_observed"] += 1
                    counts["equal_repeated_reads"] += 1
                    counts[classify(data)] += 1

    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            scan(descriptor, 0)
        finally:
            os.close(descriptor)
    except OSError:
        raise SidecarError("Source observation failed; no report produced") from None
    return counts
