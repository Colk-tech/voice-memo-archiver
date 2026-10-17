import errno
import os
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Never

import pytest

from pocs.source_layout.layout import LayoutError, category, inspect_layout


@pytest.mark.parametrize(
    "suffix,expected",
    [
        (".SQLITE3-WAL", "wal_candidate"),
        (".db-shm", "shm_candidate"),
        (".sqlite", "db_candidate"),
        (".m4a", "audio_candidate"),
        (".plist", "sidecar_candidate"),
        (".unknown", "other_regular"),
    ],
)
def test_hints(suffix: str, expected: str) -> None:
    assert category("private-title" + suffix) == expected


def test_tree_without_file_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = tmp_path / "private-folder"
    nested.mkdir()
    (nested / "private-title.m4a").write_bytes(b"not-an-audio-container")
    (tmp_path / "private.db").touch()
    (tmp_path / "private-link").symlink_to(nested, target_is_directory=True)
    os.mkfifo(tmp_path / "private-fifo")
    real_open = os.open
    opened: list[int] = []

    def directory_only(
        path: str | Path, flags: int, *, dir_fd: int | None = None
    ) -> int:
        assert flags & os.O_DIRECTORY
        assert flags & os.O_NOFOLLOW
        descriptor = real_open(path, flags, dir_fd=dir_fd)
        opened.append(descriptor)
        return descriptor

    monkeypatch.setattr(os, "open", directory_only)
    result = inspect_layout(tmp_path)
    assert result["entries_observed"] == 5
    assert result["directories"] == result["symlinks"] == result["special"] == 1
    assert result["audio_candidate"] == result["db_candidate"] == 1
    assert result["directories_unvisited"] == 0
    assert "private" not in str(result)
    assert len(opened) == 2
    for descriptor in opened:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    shallow = inspect_layout(tmp_path, max_depth=0, entry_limit=4)
    assert shallow["directories_unvisited"] == 1
    assert shallow["audio_candidate"] == 0


@pytest.mark.parametrize("limit,depth", [(0, 1), (10_001, 1), (1, -1), (1, 17)])
def test_bounds(tmp_path: Path, limit: int, depth: int) -> None:
    with pytest.raises(LayoutError, match="Invalid traversal bounds"):
        inspect_layout(tmp_path, entry_limit=limit, max_depth=depth)


def test_limit(tmp_path: Path) -> None:
    (tmp_path / "a").touch()
    (tmp_path / "b").touch()
    with pytest.raises(LayoutError, match="Entry limit exceeded"):
        inspect_layout(tmp_path, entry_limit=1)
    assert inspect_layout(tmp_path, entry_limit=2)["entries_observed"] == 2


def test_root_link_and_missing(tmp_path: Path) -> None:
    link = tmp_path / "private-link"
    link.symlink_to(tmp_path, target_is_directory=True)
    for root in (link, tmp_path / "private-missing"):
        with pytest.raises(LayoutError, match="Source metadata traversal failed"):
            inspect_layout(root)


def test_failure_closes_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    real_scan = os.scandir
    descriptors: list[int] = []

    def fail_nested(
        descriptor: int,
    ) -> AbstractContextManager[Iterator[os.DirEntry[str]]]:
        descriptors.append(descriptor)
        if len(descriptors) == 2:
            raise OSError(errno.EIO, "private-failure")
        return real_scan(descriptor)

    monkeypatch.setattr(os, "scandir", fail_nested)
    with pytest.raises(LayoutError) as error:
        inspect_layout(tmp_path)
    assert "private" not in str(error.value)
    assert len(descriptors) == 2
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_directory_replaced_by_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    real_open = os.open

    def swap(path: str | Path, flags: int, *, dir_fd: int | None = None) -> int:
        if dir_fd is not None:
            nested.rmdir()
            nested.symlink_to(tmp_path, target_is_directory=True)
        return real_open(path, flags, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap)
    with pytest.raises(LayoutError, match="Source metadata traversal failed"):
        inspect_layout(tmp_path)


def test_stat_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "file").touch()

    def fail(*args: object, **kwargs: object) -> Never:
        raise OSError(errno.ENOENT, "private-race")

    monkeypatch.setattr(os.DirEntry, "stat", fail)
    with pytest.raises(LayoutError, match="Source metadata traversal failed"):
        inspect_layout(tmp_path)
