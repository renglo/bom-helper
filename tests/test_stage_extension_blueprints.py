#!/usr/bin/env python3
"""Stage repo-root blueprints/ into package/<import>/blueprints/ without moving git source."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from stage_extension_blueprints import (  # noqa: E402
    find_import_package,
    stage_extension_blueprints,
)


def _ext_tree(tmp: Path) -> Path:
    root = tmp / "data"
    (root / "blueprints").mkdir(parents=True)
    (root / "package" / "data").mkdir(parents=True)
    (root / "package" / "data" / "__init__.py").write_text("", encoding="utf-8")
    (root / "blueprints" / "data_onboardings.json").write_text(
        json.dumps({"handle": "irma", "name": "data_onboardings", "version": "0.0.1"}),
        encoding="utf-8",
    )
    return root


class StageExtensionBlueprintsTests(unittest.TestCase):
    def test_copies_json_into_import_package(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = _ext_tree(Path(raw))
            dest = stage_extension_blueprints(extension_root=root)
            self.assertIsNotNone(dest)
            staged = dest / "data_onboardings.json"
            self.assertTrue(staged.is_file())
            self.assertTrue((root / "blueprints" / "data_onboardings.json").is_file())
            payload = json.loads(staged.read_text(encoding="utf-8"))
            self.assertEqual(payload["name"], "data_onboardings")

    def test_noop_without_blueprints(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "empty"
            (root / "package" / "foo").mkdir(parents=True)
            (root / "package" / "foo" / "__init__.py").write_text("", encoding="utf-8")
            self.assertIsNone(stage_extension_blueprints(extension_root=root))

    def test_finds_import_package(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            package = Path(raw) / "package"
            (package / "data").mkdir(parents=True)
            (package / "data" / "__init__.py").write_text("", encoding="utf-8")
            (package / "data.egg-info").mkdir()
            self.assertEqual(find_import_package(package).name, "data")


if __name__ == "__main__":
    unittest.main()
