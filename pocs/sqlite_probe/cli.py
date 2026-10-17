"""Explicit-path offline PoC CLI."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from pocs.sqlite_probe.probe import (
    ProbeError,
    probe_database,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe an explicit SQLite copy")
    parser.add_argument("--database", required=True, type=Path)
    args = parser.parse_args()
    try:
        inventory = probe_database(args.database)
    except ProbeError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "probe_version": 1,
                "acquisition_completeness": "UNKNOWN",
                "disposal_enabled": False,
                **asdict(inventory),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
