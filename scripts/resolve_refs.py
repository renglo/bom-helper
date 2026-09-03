#!/usr/bin/env python3
"""Read a BOM JSON file and write checkout refs to $GITHUB_OUTPUT.

Usage:
    python scripts/resolve_refs.py bom/v0.0.1.json
    python scripts/resolve_refs.py handlers_bom/v0.0.1.json

Prefer scripts/checkout_bom.py in workflows. This script remains for
local inspection: it emits one <name>_ref per repo in the JSON.

Handlers BOM files may also set:
    deploy_stage=production
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from bom_manifest import load_bom, output_var_name, resolve_specs


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve BOM JSON refs for GitHub Actions")
    parser.add_argument("bom_file", help="Path to bom/vX.Y.Z.json or handlers_bom/vX.Y.Z.json")
    args = parser.parse_args()

    bom_file = Path(args.bom_file)
    try:
        data = load_bom(bom_file)
        specs = resolve_specs(bom_file, data)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    github_output = os.environ.get("GITHUB_OUTPUT", "")
    lines: list[str] = []

    for spec in specs:
        output_var = output_var_name(spec.key)
        lines.append(f"{output_var}={spec.ref}")
        print(f"  {spec.key} -> {output_var}={spec.ref}  path={spec.path}")

    deploy_stage = str(data.get("deploy_stage", "")).strip()
    if deploy_stage:
        lines.append(f"deploy_stage={deploy_stage}")
        print(f"  deploy_stage -> deploy_stage={deploy_stage}")

    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    else:
        print("\n--- GITHUB_OUTPUT (dry run) ---")
        print("\n".join(lines))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
