"""Explicit-root metadata traversal with fixed, content-free output."""

import argparse
import json
import sys
from pathlib import Path

from pocs.source_layout.layout import LayoutError, inspect_layout


def main() -> int:
    parser = argparse.ArgumentParser(description="Metadata-only source layout hints")
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--entry-limit", type=int, default=10_000)
    args = parser.parse_args()
    try:
        counts = inspect_layout(
            args.source_root, max_depth=args.max_depth, entry_limit=args.entry_limit
        )
    except LayoutError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "probe_version": 1,
                "classification": "filename_hints_only",
                "snapshot_consistency": "unknown",
                "acquisition_completeness": "UNKNOWN",
                "materialization": "unknown",
                "disposal_enabled": False,
                "counts": counts,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
