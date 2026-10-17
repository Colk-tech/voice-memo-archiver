"""Synthetic inputs and fault injection only."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pocs.sidecar_probe import probe


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"bplist00bad", "binary_plist_candidate"),
        (b" <?xml junk", "xml_plist_candidate"),
        (b"<plist", "xml_plist_candidate"),
        (b" {bad", "json_candidate"),
        (b"[", "json_candidate"),
        (b"", "other"),
        (b"private", "other"),
    ],
)
def test_classify(data: bytes, expected: str) -> None:
    assert probe.classify(data) == expected


def test_tree(tmp_path: Path) -> None:
    child = tmp_path / "child"
    child.mkdir()
    (child / "private.plist").write_bytes(b"bplist00")
    (child / "private.json").write_bytes(b"{}")
    (tmp_path / "private.xml").write_bytes(b"<plist")
    (tmp_path / "unknown.plist").write_bytes(b"unknown")
    (tmp_path / "audio.m4a").write_bytes(b"private")
    (tmp_path / "db.sqlite").write_bytes(b"private")
    (tmp_path / "link.plist").symlink_to(child / "private.plist")
    os.mkfifo(tmp_path / "fifo.plist")
    report = probe.inspect_sidecars(tmp_path)
    assert report == {
        "files_observed": 4,
        "equal_repeated_reads": 4,
        "binary_plist_candidate": 1,
        "xml_plist_candidate": 1,
        "json_candidate": 1,
        "other": 1,
    }
    assert "private" not in repr(report)


@pytest.mark.parametrize(
    "bounds",
    [
        {"entry_limit": 0},
        {"max_depth": 5},
        {"file_limit": 0},
        {"total_limit": 0},
    ],
)
def test_invalid(tmp_path: Path, bounds: dict[str, int]) -> None:
    with pytest.raises(probe.SidecarError, match="Invalid"):
        probe.inspect_sidecars(tmp_path, **bounds)


@pytest.mark.parametrize(
    "bound", ["entry_limit", "max_depth", "file_limit", "total_limit"]
)
def test_bounds(tmp_path: Path, bound: str) -> None:
    if bound == "max_depth":
        (tmp_path / "child").mkdir()
        value = 0
    else:
        (tmp_path / "a.plist").write_bytes(b"123")
        (tmp_path / "b.plist").write_bytes(b"123")
        value = 1 if bound == "entry_limit" else 4
        if bound == "file_limit":
            value = 2
    with pytest.raises(probe.SidecarError, match="limit exceeded"):
        probe.inspect_sidecars(tmp_path, **{bound: value})


def test_source_error(tmp_path: Path) -> None:
    with pytest.raises(probe.SidecarError, match="^Source observation failed"):
        probe.inspect_sidecars(tmp_path / "private")
    link = tmp_path / "link"
    link.symlink_to(tmp_path)
    with pytest.raises(probe.SidecarError):
        probe.inspect_sidecars(link)


def test_read_bound() -> None:
    with (
        patch.object(os, "read", return_value=b"123"),
        pytest.raises(probe.SidecarError, match="byte limit"),
    ):
        probe._read(1, 2)
    with patch.object(os, "read", side_effect=[b"123", b""]):
        assert probe._read(1, 3) == b"123"


@pytest.mark.parametrize(
    "fault", ["opened", "special", "read", "length", "after", "entry"]
)
def test_file_races(tmp_path: Path, fault: str) -> None:
    target = tmp_path / "a.plist"
    target.write_bytes(b"{}")
    before = target.stat()
    other = tmp_path / "other"
    other.write_bytes(b"x")
    changed = other.stat()
    if fault == "special":
        changed = tmp_path.stat()
    parent = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        if fault in {"opened", "special"}:
            with (
                patch.object(os, "fstat", return_value=changed),
                pytest.raises(probe.SidecarError, match="Source changed"),
            ):
                probe._observe(parent, target.name, before, 10)
        elif fault in {"read", "length"}:
            reads = [b"{}", b"[]"] if fault == "read" else [b"x", b"x"]
            with (
                patch.object(probe, "_read", side_effect=reads),
                pytest.raises(probe.SidecarError, match="Source changed"),
            ):
                probe._observe(parent, target.name, before, 10)
        elif fault == "after":
            with (
                patch.object(os, "fstat", side_effect=[before, changed]),
                pytest.raises(probe.SidecarError, match="Source changed"),
            ):
                probe._observe(parent, target.name, before, 10)
        else:
            with (
                patch.object(os, "stat", return_value=changed),
                pytest.raises(probe.SidecarError, match="Source changed"),
            ):
                probe._observe(parent, target.name, before, 10)
    finally:
        os.close(parent)


def test_directory_race(tmp_path: Path) -> None:
    (tmp_path / "child").mkdir()
    with (
        patch.object(os, "fstat", return_value=tmp_path.stat()),
        pytest.raises(probe.SidecarError, match="Source changed"),
    ):
        probe.inspect_sidecars(tmp_path)


def test_read_failure(tmp_path: Path) -> None:
    (tmp_path / "a.plist").write_bytes(b"{}")
    with (
        patch.object(os, "read", side_effect=OSError("private")),
        pytest.raises(probe.SidecarError, match="^Source observation failed"),
    ):
        probe.inspect_sidecars(tmp_path)


def test_only_sidecars_opened_readonly(tmp_path: Path) -> None:
    for name in ("a.sqlite", "a.sqlite-wal", "a.sqlite-shm", "a.m4a", "a.txt"):
        (tmp_path / name).write_bytes(b"private")
    (tmp_path / "a.json").write_bytes(b"{}")
    original = os.open
    calls: list[tuple[str | os.PathLike[str], int]] = []

    def track(
        path: str | os.PathLike[str], flags: int, *, dir_fd: int | None = None
    ) -> int:
        calls.append((path, flags))
        return original(path, flags, dir_fd=dir_fd)

    with patch.object(os, "open", side_effect=track):
        assert probe.inspect_sidecars(tmp_path)["files_observed"] == 1
    assert [str(path) for path, _ in calls] == [str(tmp_path), "a.json"]
    for _, flags in calls:
        assert flags & os.O_NOFOLLOW
        assert not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
    assert calls[-1][1] & os.O_NONBLOCK
