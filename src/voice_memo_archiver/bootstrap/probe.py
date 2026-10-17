"""Explicit-path offline probe composition root."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from voice_memo_archiver.infrastructure.source.sqlite_probe import (
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
