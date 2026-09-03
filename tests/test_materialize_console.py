#!/usr/bin/env python3
"""Tests for unpacking a pinned @renglo/console tarball."""

from __future__ import annotations

import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from materialize_console import materialize  # noqa: E402


def _tarball(path: Path, *, name: str = "@renglo/console") -> Path:
    pkg = path / "src"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text(
        json.dumps({"name": name, "version": "0.0.3"}),
        encoding="utf-8",
    )
    (pkg / "package-lock.json").write_text("{}", encoding="utf-8")
    tgz = path / "renglo-console-0.0.3.tgz"
    with tarfile.open(tgz, "w:gz") as tf:
        tf.add(pkg, arcname="package")
    return tgz


class MaterializeConsoleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = Path(tempfile.mkdtemp())

    def test_unpacks_host_into_console(self) -> None:
        tgz = _tarball(self._dir / "pack")
        dest = self._dir / "ws"
        dest.mkdir()
        result = materialize(dest, "@renglo/console@0.0.3", tarball=tgz)
        self.assertEqual(result, "unpacked")
        pkg = json.loads((dest / "console" / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(pkg["name"], "@renglo/console")
        self.assertTrue((dest / "console" / "package-lock.json").is_file())

    def test_skips_when_console_already_present(self) -> None:
        dest = self._dir / "ws"
        console = dest / "console"
        console.mkdir(parents=True)
        (console / "package.json").write_text(
            json.dumps({"name": "@renglo/console", "version": "from-git"}),
            encoding="utf-8",
        )
        result = materialize(dest, "@renglo/console@0.0.3", tarball=self._dir / "missing.tgz")
        self.assertEqual(result, "skipped")
        pkg = json.loads((console / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(pkg["version"], "from-git")

    def test_rejects_dirty_console_directory(self) -> None:
        dest = self._dir / "ws"
        console = dest / "console"
        console.mkdir(parents=True)
        (console / "notes.txt").write_text("leftover", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            materialize(dest, "@renglo/console@0.0.3", tarball=self._dir / "missing.tgz")

    def test_rejects_wrong_package_name(self) -> None:
        tgz = _tarball(self._dir / "pack", name="@renglo/data")
        dest = self._dir / "ws"
        dest.mkdir()
        with self.assertRaises(RuntimeError):
            materialize(dest, "@renglo/console@0.0.3", tarball=tgz)

    def test_replaces_placeholder_console_dir(self) -> None:
        dest = self._dir / "ws"
        console = dest / "console"
        console.mkdir(parents=True)
        (console / ".keep").write_text("", encoding="utf-8")
        tgz = _tarball(self._dir / "pack")
        result = materialize(dest, "@renglo/console@0.0.3", tarball=tgz)
        self.assertEqual(result, "unpacked")
        self.assertFalse((dest / "console" / ".keep").exists())


if __name__ == "__main__":
    unittest.main()
