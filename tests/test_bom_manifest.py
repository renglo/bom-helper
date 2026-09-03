#!/usr/bin/env python3
"""Unit tests for BOM JSON v2 (python / npm pins + git repos)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from bom_manifest import (  # noqa: E402
    checkout_specs,
    ci_outputs,
    console_dependency_specs,
    console_host_spec,
    load_bom,
    local_npm_install_paths,
    npm_extension_handles,
    npm_install_specs,
    package_pins,
    pipeline_has_work,
    python_install_specs,
    resolve_specs,
    repos_skipped_by_pins,
)


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class BomManifestV2Tests(unittest.TestCase):
    def test_v1_repos_only_still_loads(self) -> None:
        path = _write(
            Path(self._tmp("v1.json")),
            {
                "version": "v0.0.9",
                "repos": {
                    "renglo/renglo-lib": {"commit": "abc"},
                    "renglo/data": {"commit": "def"},
                },
            },
        )
        data = load_bom(path)
        specs = resolve_specs(path, data)
        backend = checkout_specs(specs, "backend", data)
        self.assertEqual({s.key for s in backend}, {"renglo/renglo-lib", "renglo/data"})
        self.assertEqual(python_install_specs(data), [])

    def test_python_pin_skips_core_clone(self) -> None:
        path = _write(
            Path(self._tmp("v2.json")),
            {
                "version": "v0.1.0",
                "python": {"renglo-lib": "1.0.0", "renglo-api": "1.0.0"},
                "repos": {
                    "renglo/renglo-lib": {"commit": "abc"},
                    "renglo/renglo-api": {"commit": "def"},
                    "renglo/data": {"commit": "ghi"},
                },
            },
        )
        data = load_bom(path)
        specs = resolve_specs(path, data)
        backend = checkout_specs(specs, "backend", data)
        self.assertEqual([s.key for s in backend], ["renglo/data"])
        self.assertEqual(
            python_install_specs(data),
            ["renglo-lib==1.0.0", "renglo-api==1.0.0"],
        )
        self.assertEqual(
            repos_skipped_by_pins(data, "backend"),
            {"renglo/renglo-lib", "renglo/renglo-api"},
        )

    def test_extension_python_pin_skips_clone(self) -> None:
        path = _write(
            Path(self._tmp("ext.json")),
            {
                "version": "v0.2.0",
                "python": {
                    "renglo-lib": "1.0.0",
                    "renglo-api": "1.0.0",
                    "renglo-data": "1.0.0",
                },
                "repos": {
                    "renglo/data": {"commit": "aaa"},
                    "renglo/schd": {"commit": "bbb"},
                },
            },
        )
        data = load_bom(path)
        specs = resolve_specs(path, data)
        backend = checkout_specs(specs, "backend", data)
        self.assertEqual([s.key for s in backend], ["renglo/schd"])
        self.assertIn("renglo-data==1.0.0", python_install_specs(data))
        self.assertIn("renglo/data", repos_skipped_by_pins(data, "backend"))

    def test_python_only_bom_is_valid_for_backend(self) -> None:
        path = _write(
            Path(self._tmp("python-only.json")),
            {"version": "v0.2.0", "python": {"renglo-lib": "1.0.0"}},
        )
        data = load_bom(path)
        specs = resolve_specs(path, data)
        backend = checkout_specs(specs, "backend", data)
        self.assertEqual(backend, [])
        self.assertTrue(pipeline_has_work("backend", backend, data))

    def test_empty_bom_rejected(self) -> None:
        path = _write(Path(self._tmp("empty.json")), {"version": "v0.0.0"})
        with self.assertRaises(ValueError):
            load_bom(path)

    def test_npm_pin_skips_console_clone(self) -> None:
        path = _write(
            Path(self._tmp("npm.json")),
            {
                "version": "v0.1.0",
                "npm": {"@renglo/data": "1.0.0"},
                "repos": {
                    "renglo/console": {"commit": "aaa"},
                    "renglo/data": {"commit": "bbb"},
                },
            },
        )
        data = load_bom(path)
        specs = resolve_specs(path, data)
        console = checkout_specs(specs, "console", data)
        self.assertEqual([s.key for s in console], ["renglo/console"])
        self.assertEqual(npm_install_specs(data), ["@renglo/data@1.0.0"])
        self.assertEqual(package_pins(data, "npm"), {"@renglo/data": "1.0.0"})

    def test_wl_repo_is_console_only_at_stanley_wl_path(self) -> None:
        path = _write(
            Path(self._tmp("wl.json")),
            {
                "version": "v0.1.4",
                "repos": {
                    "renglo/console": {"commit": "aaa"},
                    "renglo/stanley-wl": {"branch": "main"},
                },
            },
        )
        data = load_bom(path)
        specs = resolve_specs(path, data)
        wl = next(s for s in specs if s.key == "renglo/stanley-wl")
        self.assertEqual(wl.path, "stanley-wl")
        self.assertEqual(wl.pipelines, frozenset({"console"}))
        self.assertEqual(
            [s.key for s in checkout_specs(specs, "console", data)],
            ["renglo/console", "renglo/stanley-wl"],
        )
        self.assertEqual(checkout_specs(specs, "backend", data), [])

    def test_stanley_wl_npm_pin_skips_clone(self) -> None:
        path = _write(
            Path(self._tmp("wl-pin.json")),
            {
                "version": "v0.1.4",
                "npm": {"@stanley/wl": "0.0.1"},
                "repos": {
                    "renglo/console": {"commit": "aaa"},
                    "renglo/stanley-wl": {"branch": "main"},
                },
            },
        )
        data = load_bom(path)
        specs = resolve_specs(path, data)
        self.assertEqual(
            [s.key for s in checkout_specs(specs, "console", data)],
            ["renglo/console"],
        )

    def test_console_host_pin_is_excluded_from_ci_npm_specs(self) -> None:
        path = _write(
            Path(self._tmp("console-host.json")),
            {
                "version": "v0.1.8",
                "npm": {
                    "@renglo/console": "0.0.3",
                    "@stanley/wl": "0.0.1",
                    "@renglo/data": "0.0.2",
                },
            },
        )
        data = load_bom(path)
        self.assertEqual(console_host_spec(data), "@renglo/console@0.0.3")
        self.assertEqual(
            console_dependency_specs(data),
            ["@stanley/wl@0.0.1", "@renglo/data@0.0.2"],
        )
        self.assertEqual(
            npm_install_specs(data),
            ["@renglo/console@0.0.3", "@stanley/wl@0.0.1", "@renglo/data@0.0.2"],
        )
        outputs = ci_outputs(data, [])
        self.assertEqual(outputs["console_host_spec"], "@renglo/console@0.0.3")
        self.assertEqual(outputs["has_console_pin"], "true")
        self.assertEqual(outputs["npm_specs"], "@stanley/wl@0.0.1 @renglo/data@0.0.2")
        self.assertEqual(outputs["has_npm_pins"], "true")

    def test_npm_extension_handles_ignore_scope_and_skip_host_and_wl(self) -> None:
        path = _write(
            Path(self._tmp("multi-publisher.json")),
            {
                "version": "v0.2.0",
                "npm": {
                    "@renglo/console": "0.0.4",
                    "@renglo/data": "0.0.2",
                    "@something/wl": "0.0.1",
                    "@something/casting": "1.0.0",
                    "@acme/lab": "2.0.0",
                },
            },
        )
        data = load_bom(path)
        self.assertEqual(
            npm_extension_handles(data),
            ["data", "casting", "lab"],
        )

    def test_console_only_pin_has_no_dependency_specs(self) -> None:
        path = _write(
            Path(self._tmp("console-only.json")),
            {"version": "v0.1.8", "npm": {"@renglo/console": "0.0.3"}},
        )
        data = load_bom(path)
        outputs = ci_outputs(data, [])
        self.assertEqual(outputs["has_console_pin"], "true")
        self.assertEqual(outputs["has_npm_pins"], "false")
        self.assertEqual(outputs["npm_specs"], "")

    def test_local_npm_install_paths_skips_console_and_extensions(self) -> None:
        dest = Path(self._tmp("dest"))
        (dest / "console").mkdir(parents=True)
        (dest / "console" / "package.json").write_text("{}", encoding="utf-8")
        (dest / "stanley-wl").mkdir(parents=True)
        (dest / "stanley-wl" / "package.json").write_text("{}", encoding="utf-8")
        (dest / "extensions" / "data").mkdir(parents=True)
        (dest / "extensions" / "data" / "package.json").write_text("{}", encoding="utf-8")
        path = _write(
            Path(self._tmp("wl-local.json")),
            {
                "version": "v0.1.4",
                "repos": {
                    "renglo/console": {"commit": "aaa"},
                    "renglo/stanley-wl": {"branch": "main"},
                    "renglo/data": {"commit": "bbb"},
                },
            },
        )
        data = load_bom(path)
        specs = resolve_specs(path, data)
        console = checkout_specs(specs, "console", data)
        found = local_npm_install_paths(dest, console)
        self.assertEqual(found, [str((dest / "stanley-wl").resolve())])

    def _tmp(self, name: str) -> str:
        folder = Path(self.id().replace(".", "_"))
        # unittest does not give us tmp_path; use a folder next to this file's cwd via mkdtemp
        if not hasattr(self, "_dir"):
            import tempfile

            self._dir = Path(tempfile.mkdtemp())
        return str(self._dir / name)


if __name__ == "__main__":
    unittest.main()
