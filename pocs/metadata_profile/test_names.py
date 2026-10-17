import os
from pathlib import Path
from typing import Never

import pytest

from pocs.metadata_profile.names import HintsError, collect_hints


def test_private_names_and_directory_only_opens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = tmp_path / "private-folder"
    nested.mkdir()
    for parent in (tmp_path, nested):
        (parent / "private.M4A").write_bytes(b"must not be opened")
        (parent / "private.plist").touch()
    (tmp_path / "private.db").touch()
    (tmp_path / "private-link.m4a").symlink_to(nested)
    os.mkfifo(tmp_path / "private-fifo.m4a")
    real_open = os.open
    descriptors: list[int] = []

    def directory_only(
        path: str | Path, flags: int, *, dir_fd: int | None = None
    ) -> int:
        assert flags & os.O_DIRECTORY
        assert flags & os.O_NOFOLLOW
        descriptor = real_open(path, flags, dir_fd=dir_fd)
        descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(os, "open", directory_only)
    result = collect_hints(tmp_path)
    assert result.audio == ("private.M4A", "private.M4A")
    assert result.sidecar == ("private.plist", "private.plist")
    assert result.audio_entries == result.sidecar_entries == 2
    assert "private" not in repr(result)
    assert len(descriptors) == 2
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


@pytest.mark.parametrize("limit,depth", [(0, 1), (10_001, 1), (1, -1), (1, 17)])
def test_bounds(tmp_path: Path, limit: int, depth: int) -> None:
    with pytest.raises(HintsError, match="Invalid traversal bounds"):
        collect_hints(tmp_path, entry_limit=limit, max_depth=depth)


def test_limits(tmp_path: Path) -> None:
    (tmp_path / "a.m4a").touch()
    assert collect_hints(tmp_path, entry_limit=1).audio_entries == 1
    (tmp_path / "b").touch()
    with pytest.raises(HintsError, match="Entry limit exceeded"):
        collect_hints(tmp_path, entry_limit=1)
    (tmp_path / "nested").mkdir()
    with pytest.raises(HintsError, match="Depth limit exceeded"):
        collect_hints(tmp_path, max_depth=0)


def test_missing_and_symlink_roots(tmp_path: Path) -> None:
    link = tmp_path / "private-link"
    link.symlink_to(tmp_path, target_is_directory=True)
    for root in (link, tmp_path / "private-missing"):
        with pytest.raises(HintsError) as error:
            collect_hints(root)
        assert str(error.value) == "Source name traversal failed; no report produced"


def test_stat_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "private.m4a").touch()

    def fail(*args: object, **kwargs: object) -> Never:
        raise OSError("private-details")

    monkeypatch.setattr(os.DirEntry, "stat", fail)
    with pytest.raises(HintsError) as error:
        collect_hints(tmp_path)
    assert "private" not in str(error.value)


@pytest.mark.parametrize("replacement", ["directory", "symlink"])
def test_directory_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    original = tmp_path / "original"
    real_open = os.open
    descriptors: list[int] = []

    def swap(path: str | Path, flags: int, *, dir_fd: int | None = None) -> int:
        if dir_fd is not None:
            nested.rename(original)
            if replacement == "directory":
                nested.mkdir()
            else:
                nested.symlink_to(original, target_is_directory=True)
        descriptor = real_open(path, flags, dir_fd=dir_fd)
        descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(os, "open", swap)
    with pytest.raises(HintsError):
        collect_hints(tmp_path)
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_case_sensitive_basenames(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "PRIVATE.m4a").touch()
    (second / "private.m4a").touch()
    result = collect_hints(tmp_path)
    assert sorted(result.audio) == ["PRIVATE.m4a", "private.m4a"]
    assert result.audio_entries == 2
    assert result.sidecar == ()
