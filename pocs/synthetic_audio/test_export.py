"""Synthetic-only byte export and fault injection tests."""

import hashlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pocs.synthetic_audio import export


def test_export(tmp_path: Path) -> None:
    source, destination = tmp_path / "source", tmp_path / "destination"
    data = b"synthetic\x00\xff"
    source.write_bytes(data)
    result = export.export_audio(source, destination)
    assert result == export.ExportEvidence(
        len(data), hashlib.sha256(data).hexdigest(), True
    )
    assert destination.read_bytes() == source.read_bytes() == data
    assert destination.stat().st_mode & 0o777 == 0o600


def test_nonoverwrite(tmp_path: Path) -> None:
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_bytes(b"synthetic")
    destination.write_bytes(b"existing")
    with pytest.raises(export.ExportError, match="^Synthetic audio export failed$"):
        export.export_audio(source, destination)
    assert destination.read_bytes() == b"existing"


@pytest.mark.parametrize("kind", ["symlink", "fifo", "directory", "missing"])
def test_unsafe_source(tmp_path: Path, kind: str) -> None:
    source = tmp_path / "source"
    if kind == "symlink":
        source.symlink_to(tmp_path)
    elif kind == "fifo":
        os.mkfifo(source)
    elif kind == "directory":
        source.mkdir()
    with pytest.raises(export.ExportError):
        export.export_audio(source, tmp_path / "destination")
    assert not (tmp_path / "destination").exists()


def test_initial_size_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"123")
    monkeypatch.setattr(export, "MAX_BYTES", 2)
    with pytest.raises(export.ExportError, match="byte limit"):
        export.export_audio(source, tmp_path / "destination")


def test_read_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(export, "MAX_BYTES", 2)
    with (
        patch.object(os, "read", return_value=b"123"),
        pytest.raises(export.ExportError, match="byte limit"),
    ):
        export._read(1)


@pytest.mark.parametrize(
    "fault", ["opened", "special", "read", "length", "after", "leaf"]
)
def test_changes(tmp_path: Path, fault: str) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"123")
    before = source.stat()
    other = tmp_path / "other"
    other.write_bytes(b"other")
    changed = other.stat() if fault != "special" else tmp_path.stat()
    destination = tmp_path / "destination"
    if fault in {"opened", "special"}:
        with (
            patch.object(os, "fstat", return_value=changed),
            pytest.raises(export.ExportError, match="source changed"),
        ):
            export.export_audio(source, destination)
    elif fault in {"read", "length"}:
        reads = [b"123", b"456"] if fault == "read" else [b"1", b"1"]
        with (
            patch.object(export, "_read", side_effect=reads),
            pytest.raises(export.ExportError, match="source changed"),
        ):
            export.export_audio(source, destination)
    elif fault == "after":
        with (
            patch.object(os, "fstat", side_effect=[before, changed]),
            pytest.raises(export.ExportError, match="source changed"),
        ):
            export.export_audio(source, destination)
    else:
        with (
            patch.object(Path, "stat", side_effect=[before, changed]),
            pytest.raises(export.ExportError, match="source changed"),
        ):
            export.export_audio(source, destination)
    assert not destination.exists()


@pytest.mark.parametrize("corruption", [b"", b"BAD"])
def test_readback_corruption(tmp_path: Path, corruption: bytes) -> None:
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_bytes(b"123")
    original_fsync = os.fsync

    def corrupt(descriptor: int) -> None:
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.write(descriptor, corruption)
        original_fsync(descriptor)

    with (
        patch.object(os, "fsync", side_effect=corrupt),
        pytest.raises(export.ExportError, match="readback failed"),
    ):
        export.export_audio(source, destination)
    assert destination.exists()
