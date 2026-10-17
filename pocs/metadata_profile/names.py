"""Keep filename association hints in memory without opening file contents."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from pocs.source_layout.layout import category


class HintsError(Exception):
    """Fixed failure text; callers must discard partial observations."""


@dataclass(frozen=True, repr=False)
class FileHints:
    """Private basenames; counts include duplicate basenames across folders."""

    audio: tuple[str, ...]
    sidecar: tuple[str, ...]
    audio_entries: int
    sidecar_entries: int


def collect_hints(
    root: Path, *, entry_limit: int = 10_000, max_depth: int = 4
) -> FileHints:
    """Observe names only; this is neither a snapshot nor format verification."""
    if not 1 <= entry_limit <= 10_000 or not 0 <= max_depth <= 16:
        raise HintsError("Invalid traversal bounds")
    audio: list[str] = []
    sidecar: list[str] = []
    observed = audio_entries = sidecar_entries = 0

    def scan(descriptor: int, depth: int) -> None:
        nonlocal observed, audio_entries, sidecar_entries
        with os.scandir(descriptor) as entries:
            for entry in entries:
                if observed == entry_limit:
                    raise HintsError("Entry limit exceeded; no report produced")
                observed += 1
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    if depth == max_depth:
                        raise HintsError("Depth limit exceeded; no report produced")
                    child = os.open(
                        entry.name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=descriptor,
                    )
                    try:
                        opened = os.fstat(child)
                        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                            raise HintsError("Directory changed; no report produced")
                        scan(child, depth + 1)
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode):
                    kind = category(entry.name)
                    if kind == "audio_candidate":
                        audio.append(entry.name)
                        audio_entries += 1
                    elif kind == "sidecar_candidate":
                        sidecar.append(entry.name)
                        sidecar_entries += 1

    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            scan(descriptor, 0)
        finally:
            os.close(descriptor)
    except OSError:
        raise HintsError("Source name traversal failed; no report produced") from None
    return FileHints(tuple(audio), tuple(sidecar), audio_entries, sidecar_entries)
