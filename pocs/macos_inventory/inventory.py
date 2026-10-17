"""Read system/app versions and count directory entries without reading files."""

import os
import plistlib
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from xml.parsers.expat import ExpatError

SYSTEM_INFO = Path("/System/Library/CoreServices/SystemVersion.plist")
APP_INFO = Path("/System/Applications/VoiceMemos.app/Contents/Info.plist")


class InventoryError(Exception):
    """Content-free failure suitable for terminal output."""


@dataclass(frozen=True)
class HostInventory:
    product_version: str
    build_version: str
    app_bundle_id: str
    app_version: str
    app_build: str


@dataclass(frozen=True)
class DirectoryInventory:
    state: str
    entries_observed: int


def _strings(path: Path, keys: tuple[str, ...]) -> tuple[str, ...]:
    try:
        data: object = plistlib.loads(path.read_bytes())
        if not isinstance(data, dict):
            raise InventoryError("Host metadata has an unsupported structure")
        values: list[str] = []
        for key in keys:
            value: object = data.get(key)
            if not isinstance(value, str) or not value:
                raise InventoryError("Host metadata is incomplete")
            values.append(value)
        return tuple(values)
    except OSError, ValueError, plistlib.InvalidFileException, ExpatError:
        raise InventoryError("Host metadata could not be read") from None


def inspect_host(
    system_info: Path = SYSTEM_INFO, app_info: Path = APP_INFO
) -> HostInventory:
    product, build = _strings(system_info, ("ProductVersion", "ProductBuildVersion"))
    bundle, version, app_build = _strings(
        app_info,
        ("CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleVersion"),
    )
    if bundle != "com.apple.VoiceMemos":
        raise InventoryError("Unexpected application bundle")
    return HostInventory(product, build, bundle, version, app_build)


def inspect_directory(root: Path, *, entry_limit: int = 10_000) -> DirectoryInventory:
    """Count only immediate entries; never open children or follow root links.

    Listability is not evidence of materialization or snapshot consistency.
    Paths and entry names are never included in the result.
    """
    if entry_limit < 1:
        raise InventoryError("Entry limit must be positive")
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with os.scandir(descriptor) as entries:
                count = sum(1 for _ in islice(entries, entry_limit + 1))
        finally:
            os.close(descriptor)
    except FileNotFoundError:
        return DirectoryInventory("missing", 0)
    except PermissionError:
        return DirectoryInventory("permission_denied", 0)
    except NotADirectoryError:
        return DirectoryInventory("not_directory_or_symlink", 0)
    except OSError:
        return DirectoryInventory("unreadable", 0)
    if count > entry_limit:
        return DirectoryInventory("limit_exceeded", entry_limit)
    return DirectoryInventory("listable", count)
