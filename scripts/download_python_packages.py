#!/usr/bin/env python3
"""Download BOM python pins into wheels/ (CodeArtifact must already be configured)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from bom_manifest import load_bom, python_install_specs


def main() -> int:
    parser = argparse.ArgumentParser(description="pip download BOM JSON python pins")
    parser.add_argument("bom_file", help="Path to a BOM JSON file")
    parser.add_argument(
        "--dest",
        default="wheels",
        help="Directory to write wheels into (default: wheels)",
    )
    args = parser.parse_args()

    path = Path(args.bom_file)
    dest = Path(args.dest)
    try:
        data = load_bom(path)
        specs = python_install_specs(data)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not specs:
        print("No python pins in BOM JSON; nothing to download.")
        dest.mkdir(parents=True, exist_ok=True)
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {len(specs)} pin(s) into {dest.resolve()}")
    subprocess.run(
        [sys.executable, "-m", "pip", "download", "-d", str(dest), *specs],
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
