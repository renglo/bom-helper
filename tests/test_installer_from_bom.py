#!/usr/bin/env python3
"""BOM-pin installer/infra extraction (no CodeArtifact)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from installer_from_bom import (  # noqa: E402
    extract_installer,
    find_infra_root,
    handle_pin,
    materialize_peer_installers,
    slot_for_handle,
)
from catalog_slots import parse_package_catalog  # noqa: E402
from stage_extension_blueprints import stage_extension_installer  # noqa: E402


def _catalog_text() -> str:
    return """
packages:
  acmewidget:
    python: acme-widget
    repo: Org/acmewidget
bom: 0.1.0
peers:
  lab:
    compute: lambda_only
    extensions: [acmewidget]
    peers_bom: 0.0.1
    python:
      - acme-widget
"""


def _write_bom(root: Path) -> Path:
    bom = root / "acme-bom"
    bom.mkdir()
    (bom / "deploy_targets.yml").write_text(_catalog_text(), encoding="utf-8")
    pin_dir = bom / "peers_bom" / "lab"
    pin_dir.mkdir(parents=True)
    (pin_dir / "v0.0.1.json").write_text(
        json.dumps({"version": "v0.0.1", "python": {"acme-widget": "0.0.7", "renglo-lib": "0.0.4"}}),
        encoding="utf-8",
    )
    return bom


def _write_infra(folder: Path) -> None:
    infra = folder / "installer" / "infra"
    infra.mkdir(parents=True)
    (infra / "cdk_extension.json").write_text(
        json.dumps({"policy_file": "actions.json", "policy_name": "{env}-acmewidget-actions"}),
        encoding="utf-8",
    )
    (infra / "actions.json").write_text(
        json.dumps({"Version": "2012-10-17", "Statement": []}),
        encoding="utf-8",
    )


def _wheel_with_nested_infra(path: Path) -> Path:
    _write_infra(path.parent / "_src" / "acme_widget")
    infra = path.parent / "_src" / "acme_widget" / "installer" / "infra"
    with zipfile.ZipFile(path, "w") as zf:
        for child in infra.iterdir():
            zf.write(child, f"acme_widget/installer/infra/{child.name}")
    return path


def _wheel_with_top_infra(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("infra/cdk_extension.json", json.dumps({"policy_file": "actions.json"}))
        zf.writestr("infra/actions.json", json.dumps({"Version": "2012-10-17", "Statement": []}))
    return path


class InstallerFromBomTests(unittest.TestCase):
    def test_slot_and_pin(self) -> None:
        catalog = parse_package_catalog(
            "packages:\n  acmewidget:\n    python: acme-widget\n"
        )
        assert catalog is not None
        slot = slot_for_handle(catalog, "acmewidget")
        self.assertIsNotNone(slot)
        assert slot is not None
        self.assertEqual(slot.python, "acme-widget")
        with tempfile.TemporaryDirectory() as raw:
            bom = _write_bom(Path(raw))
            dist, version, pin = handle_pin(bom, "acmewidget", peer_id="lab")
            self.assertEqual(dist, "acme-widget")
            self.assertEqual(version, "0.0.7")
            self.assertTrue(pin.name.endswith("v0.0.1.json"))

    def test_extract_nested_and_top_level_infra(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            nested = extract_installer(
                _wheel_with_nested_infra(root / "acme_widget-0.0.7-py3-none-any.whl"),
                root / "out-nested",
            )
            self.assertTrue((nested / "installer" / "infra" / "cdk_extension.json").is_file())
            top = extract_installer(
                _wheel_with_top_infra(root / "other-0.0.1-py3-none-any.whl"),
                root / "out-top",
            )
            self.assertTrue((top / "installer" / "infra" / "cdk_extension.json").is_file())

    def test_missing_infra_in_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wheel = Path(raw) / "empty-0.0.1-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as zf:
                zf.writestr("empty/__init__.py", "")
            with self.assertRaises(FileNotFoundError):
                extract_installer(wheel, Path(raw) / "out")

    def test_materialize_from_artifacts_and_skip_local(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bom = _write_bom(root)
            artifacts = root / "wheels"
            artifacts.mkdir()
            _wheel_with_nested_infra(artifacts / "acme_widget-0.0.7-py3-none-any.whl")
            dest = root / "extension-actions"
            rows = materialize_peer_installers(
                bom, dest, peer_id="lab", from_artifacts=artifacts
            )
            self.assertEqual(rows[0]["source"], "package")
            self.assertEqual(rows[0]["pin"], "acme-widget==0.0.7")
            self.assertTrue((dest / "acmewidget" / "installer" / "infra" / "cdk_extension.json").is_file())

            cached = materialize_peer_installers(
                bom, dest, peer_id="lab", from_artifacts=artifacts
            )
            self.assertEqual(cached[0]["source"], "cache")

            workspace = root / "ws"
            _write_infra(workspace / "extensions" / "acmewidget")
            local = materialize_peer_installers(
                bom, dest, peer_id="lab", workspace=workspace, from_artifacts=artifacts
            )
            self.assertEqual(local[0]["source"], "local")

    def test_stage_installer_into_import_package(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "ext"
            _write_infra(root)
            pkg = root / "package" / "acme_widget"
            pkg.mkdir(parents=True)
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            dest = stage_extension_installer(extension_root=root)
            self.assertIsNotNone(dest)
            assert dest is not None
            self.assertTrue((dest / "cdk_extension.json").is_file())
            self.assertTrue((root / "installer" / "infra" / "cdk_extension.json").is_file())

    def test_find_infra_ignores_dist_info(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            decoy = root / "acme_widget-0.0.7.dist-info" / "installer" / "infra"
            decoy.mkdir(parents=True)
            (decoy / "cdk_extension.json").write_text("{}", encoding="utf-8")
            real = root / "acme_widget" / "installer" / "infra"
            real.mkdir(parents=True)
            (real / "cdk_extension.json").write_text("{}", encoding="utf-8")
            found = find_infra_root(root)
            self.assertEqual(found, root / "acme_widget")


if __name__ == "__main__":
    unittest.main()
