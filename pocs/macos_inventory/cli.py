"""Explicit-source macOS feasibility report; no recording data is read."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from pocs.macos_inventory.inventory import (
    InventoryError,
    inspect_directory,
    inspect_host,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only macOS source readiness")
    parser.add_argument("--source-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        host = inspect_host()
        directory = inspect_directory(args.source_root)
    except InventoryError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "probe_version": 1,
                "host": asdict(host),
                "source_directory": asdict(directory),
                "acquisition_completeness": "UNKNOWN",
                "materialization": "unknown",
                "disposal_enabled": False,
            },
            sort_keys=True,
        )
    )
    return 0 if directory.state == "listable" else 1


if __name__ == "__main__":
    raise SystemExit(main())
