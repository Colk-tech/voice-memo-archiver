"""Count fixed filename hints without opening regular files or following links."""

import os
import stat
from pathlib import Path


class LayoutError(Exception):
    """Sanitized failure; partial observations are not returned."""


def category(name: str) -> str:
    """Hints only: neither signatures nor recording associations are verified."""
    lower = name.lower()
    if lower.endswith((".db-wal", ".sqlite-wal", ".sqlite3-wal")):
        return "wal_candidate"
    if lower.endswith((".db-shm", ".sqlite-shm", ".sqlite3-shm")):
        return "shm_candidate"
    if lower.endswith((".db", ".sqlite", ".sqlite3")):
        return "db_candidate"
    if lower.endswith((".m4a", ".wav", ".caf", ".aiff", ".mp4", ".aac")):
        return "audio_candidate"
    if lower.endswith((".plist", ".json", ".xml")):
        return "sidecar_candidate"
    return "other_regular"


def inspect_layout(
    root: Path, *, entry_limit: int = 10_000, max_depth: int = 4
) -> dict[str, int]:
    """Depth zero scans root only; all directory opens use descriptor-relative I/O.

    Parent components of the explicit root are operator-trusted. No file data,
    extended attributes, sizes, timestamps or arbitrary suffixes are returned.
    Enumeration is a sequence of observations, never an atomic snapshot.
    """
    if not 1 <= entry_limit <= 10_000 or not 0 <= max_depth <= 16:
        raise LayoutError("Invalid traversal bounds")
    counts = dict.fromkeys(
        (
            "entries_observed",
            "directories",
            "directories_unvisited",
            "symlinks",
            "special",
            "db_candidate",
            "wal_candidate",
            "shm_candidate",
            "audio_candidate",
            "sidecar_candidate",
            "other_regular",
        ),
        0,
    )

    def scan(descriptor: int, depth: int) -> None:
        with os.scandir(descriptor) as entries:
            for entry in entries:
                if counts["entries_observed"] == entry_limit:
                    raise LayoutError("Entry limit exceeded; no report produced")
                counts["entries_observed"] += 1
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISDIR(mode):
                    counts["directories"] += 1
                    if depth == max_depth:
                        counts["directories_unvisited"] += 1
                    else:
                        child = os.open(
                            entry.name,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=descriptor,
                        )
                        try:
                            scan(child, depth + 1)
                        finally:
                            os.close(child)
                elif stat.S_ISLNK(mode):
                    counts["symlinks"] += 1
                elif stat.S_ISREG(mode):
                    counts[category(entry.name)] += 1
                else:
                    counts["special"] += 1

    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            scan(descriptor, 0)
        finally:
            os.close(descriptor)
    except OSError:
        raise LayoutError(
            "Source metadata traversal failed; no report produced"
        ) from None
    return counts
