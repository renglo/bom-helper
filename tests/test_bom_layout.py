#!/usr/bin/env python3
"""Tests for three-BOM layout (Console / Hub / Peer)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from bom_layout import (  # noqa: E402
    Placement,
    console_npm_for_placement,
    load_placement,
    parse_placement_text,
    split_master_bom,
    validate_split,
    write_split_boms,
)
from catalog_slots import PackageSlot, parse_package_catalog  # noqa: E402


class BomLayoutTests(unittest.TestCase):
    def test_parse_placement(self) -> None:
        text = """
hub:
  python:
    - renglo-gro
    - renglo-schd
peers:
  lab:
    extensions: [foo]
    python:
      - acme-lab
"""
        placement = parse_placement_text(text)
        self.assertEqual(placement.hub_python, ("renglo-gro", "renglo-schd"))
        self.assertEqual(placement.peers["lab"], ("acme-lab",))

    def test_split_hub_console_peer(self) -> None:
        catalog = [
            PackageSlot(id="console", npm="@renglo/console"),
            PackageSlot(id="wl", python="acme-wl", npm="@acme/wl"),
            PackageSlot(id="gro", python="renglo-gro", npm="@renglo/gro"),
            PackageSlot(id="lab", python="acme-lab", npm="@acme/lab"),
        ]
        placement = Placement(
            hub_python=("renglo-gro",),
            peers={"lab": ("acme-lab", "renglo-gro")},
        )
        master = {
            "version": "v1.0.0",
            "python": {
                "renglo-lib": "1.0.0",
                "renglo-api": "2.0.0",
                "acme-wl": "0.1.0",
                "renglo-gro": "3.0.0",
                "acme-lab": "4.0.0",
            },
            "npm": {
                "@renglo/console": "9.0.0",
                "@acme/wl": "0.1.0",
                "@renglo/gro": "3.0.0",
                "@acme/lab": "4.0.0",
            },
        }
        hub, console, peers = split_master_bom(master, placement=placement, catalog=catalog)
        self.assertIn("renglo-api", hub["python"])
        self.assertIn("renglo-gro", hub["python"])
        self.assertNotIn("acme-lab", hub["python"])
        self.assertIn("@acme/lab", console["npm"])
        self.assertIn("@renglo/gro", console["npm"])
        self.assertIn("@renglo/console", console["npm"])
        self.assertIn("acme-lab", peers["lab"]["python"])
        self.assertIn("renglo-gro", peers["lab"]["python"])

    def test_handler_only_on_hub_skips_console_npm(self) -> None:
        catalog = [
            PackageSlot(id="svc", python="acme-svc"),
        ]
        placement = Placement(hub_python=("acme-svc",))
        npm = console_npm_for_placement(
            {"@renglo/console": "1.0.0"},
            placement=placement,
            catalog=catalog,
        )
        self.assertEqual(list(npm.keys()), ["@renglo/console"])

    def test_write_and_validate_roundtrip(self) -> None:
        root = Path(self._tmp()) / "acme-bom"
        root.mkdir()
        (root / "deploy_targets.yml").write_text(
            """
bom: 1.0.0
console_bom: 1.0.0
packages:
  console:
    npm: "@renglo/console"
  wl:
    python: acme-wl
    npm: "@acme/wl"
  gro:
    python: renglo-gro
    npm: "@renglo/gro"
  lab:
    python: acme-lab
    npm: "@acme/lab"
hub:
  python:
    - renglo-gro
peers:
  lab:
    extensions: [lab]
    python:
      - acme-lab
    peers_bom: 1.0.0
""",
            encoding="utf-8",
        )
        master = {
            "version": "v1.0.0",
            "python": {
                "renglo-lib": "1.0.0",
                "renglo-api": "1.0.0",
                "acme-wl": "0.1.0",
                "renglo-gro": "3.0.0",
                "acme-lab": "4.0.0",
            },
            "npm": {
                "@renglo/console": "9.0.0",
                "@acme/wl": "0.1.0",
                "@renglo/gro": "3.0.0",
                "@acme/lab": "4.0.0",
            },
        }
        write_split_boms(root, "1.0.0", master)
        errors = validate_split(root, "1.0.0")
        self.assertEqual(errors, [])
        hub = json.loads((root / "bom/v1.0.0.json").read_text())
        self.assertIn("renglo-gro", hub["python"])
        console = json.loads((root / "console_bom/v1.0.0.json").read_text())
        self.assertIn("@acme/lab", console["npm"])

    def _tmp(self, suffix: str = "") -> str:
        import tempfile

        return tempfile.mkdtemp(suffix=suffix)


if __name__ == "__main__":
    unittest.main()
