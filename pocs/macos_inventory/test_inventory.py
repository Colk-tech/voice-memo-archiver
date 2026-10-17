import errno
import os
import plistlib
from pathlib import Path
from typing import Never

import pytest

from pocs.macos_inventory.inventory import (
    DirectoryInventory,
    InventoryError,
    inspect_directory,
    inspect_host,
)


def system_fixture(tmp_path: Path) -> tuple[Path, Path]:
    system = tmp_path / "system.plist"
    app = tmp_path / "app.plist"
    system.write_bytes(
        plistlib.dumps(
            {"ProductVersion": "27.0.1", "ProductBuildVersion": "synthetic-build"}
        )
    )
    app.write_bytes(
        plistlib.dumps(
            {
                "CFBundleIdentifier": "com.apple.VoiceMemos",
                "CFBundleShortVersionString": "4.0",
                "CFBundleVersion": "123",
            }
        )
    )
    return system, app


def test_host(tmp_path: Path) -> None:
    system, app = system_fixture(tmp_path)
    result = inspect_host(system, app)
    assert result.product_version == "27.0.1"
    assert result.build_version == "synthetic-build"
    assert result.app_version == "4.0"
    assert result.app_build == "123"


@pytest.mark.parametrize(
    "case", ["missing", "corrupt", "list", "absent", "empty", "number", "bundle"]
)
def test_invalid_host(tmp_path: Path, case: str) -> None:
    system, app = system_fixture(tmp_path)
    if case == "missing":
        system.unlink()
    elif case == "corrupt":
        system.write_bytes(b"private-invalid-plist")
    elif case == "list":
        system.write_bytes(plistlib.dumps([]))
    elif case == "bundle":
        app.write_bytes(
            plistlib.dumps(
                {
                    "CFBundleIdentifier": "private-wrong-app",
                    "CFBundleShortVersionString": "4.0",
                    "CFBundleVersion": "123",
                }
            )
        )
    else:
        value = {"absent": None, "empty": "", "number": 27}[case]
        data: dict[str, object] = {"ProductBuildVersion": "build"}
        if value is not None:
            data["ProductVersion"] = value
        system.write_bytes(plistlib.dumps(data))
    with pytest.raises(InventoryError) as error:
        inspect_host(system, app)
    assert "private" not in str(error.value)
    assert str(tmp_path) not in str(error.value)


def test_directory_counts_without_reading_children(tmp_path: Path) -> None:
    (tmp_path / "private-title.m4a").write_bytes(b"private-audio")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "not-counted").touch()
    (tmp_path / "external-link").symlink_to("/does-not-exist")
    assert inspect_directory(tmp_path) == DirectoryInventory("listable", 3)
    assert inspect_directory(nested) == DirectoryInventory("listable", 1)
    assert inspect_directory(tmp_path, entry_limit=2) == DirectoryInventory(
        "limit_exceeded", 2
    )
    assert inspect_directory(tmp_path, entry_limit=3) == DirectoryInventory(
        "listable", 3
    )


def test_root_is_not_followed(tmp_path: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    assert inspect_directory(link).state in {"not_directory_or_symlink", "unreadable"}
    file = tmp_path / "file"
    file.touch()
    assert inspect_directory(file).state == "not_directory_or_symlink"
    assert inspect_directory(tmp_path / "missing").state == "missing"


@pytest.mark.parametrize(
    "error_number,expected",
    [(errno.EACCES, "permission_denied"), (errno.EIO, "unreadable")],
)
def test_directory_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_number: int, expected: str
) -> None:
    def fail(_path: Path, _flags: int) -> int:
        raise OSError(error_number, "private-path")

    monkeypatch.setattr(os, "open", fail)
    assert inspect_directory(tmp_path) == DirectoryInventory(expected, 0)


def test_invalid_limit(tmp_path: Path) -> None:
    with pytest.raises(InventoryError, match="must be positive"):
        inspect_directory(tmp_path, entry_limit=0)


def test_malformed_xml_is_sanitized(tmp_path: Path) -> None:
    system, app = system_fixture(tmp_path)
    system.write_bytes(b'<?xml version="1.0"?><plist><dict>')
    with pytest.raises(InventoryError, match="could not be read"):
        inspect_host(system, app)


def test_scan_failure_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    descriptors: list[int] = []

    def fail(descriptor: int) -> Never:
        descriptors.append(descriptor)
        raise OSError(errno.EIO, "private-path")

    monkeypatch.setattr(os, "scandir", fail)
    assert inspect_directory(tmp_path) == DirectoryInventory("unreadable", 0)
    assert len(descriptors) == 1
    with pytest.raises(OSError) as error:
        os.fstat(descriptors[0])
    assert error.value.errno == errno.EBADF
