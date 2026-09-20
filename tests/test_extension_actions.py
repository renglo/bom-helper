#!/usr/bin/env python3
"""Catalog-driven extension actions policy resolution."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from extension_actions import (  # noqa: E402
    catalog_actions_specs,
    handle_from_extension_folder,
    hub_actions_specs,
    load_actions_spec,
    peer_actions_policy_name,
    peer_actions_specs,
)


def _write_extension(root: Path, handle: str, *, policy_name: str) -> Path:
    infra = root / "extensions" / handle / "installer" / "infra"
    infra.mkdir(parents=True)
    (infra / "cdk_extension.json").write_text(
        json.dumps(
            {
                "policy_file": "actions_tt_policy.json",
                "policy_name": policy_name,
                "policy_description": f"{handle} actions",
                "attach_policy_to_roles": ["{env}_tt_role"],
            }
        ),
        encoding="utf-8",
    )
    (infra / "actions_tt_policy.json").write_text(
        json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["logs:CreateLogGroup"],
                        "Resource": "*",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return root / "extensions" / handle


class ExtensionActionsTests(unittest.TestCase):
    def test_hub_specs_only_for_hub_python_with_installer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            bom = workspace / "ops" / "acme-bom"
            bom.mkdir(parents=True)
            _write_extension(workspace, "acmewidget", policy_name="{env}_actions_tt_policy")
            _write_extension(workspace, "acmeextra", policy_name="{env}-acmeextra-actions")
            (bom / "deploy_targets.yml").write_text(
                """
packages:
  gro:
    python: renglo-gro
  acmewidget:
    python: acme-widget
  acmeextra:
    python: acme-extra
hub:
  python:
    - renglo-gro
    - acme-widget
peers:
  lab:
    compute: fargate
    extensions: [acmewidget, acmeextra]
    peers_bom: 0.0.1
    python:
      - acme-widget
      - acme-extra
""",
                encoding="utf-8",
            )
            specs = hub_actions_specs(bom / "deploy_targets.yml", workspace)
            self.assertEqual([s.handle for s in specs], ["acmewidget"])
            self.assertEqual(specs[0].hub_policy_name("acme0813"), "acme0813_actions_tt_policy")
            all_specs = catalog_actions_specs(bom / "deploy_targets.yml", workspace)
            self.assertEqual(
                sorted(s.handle for s in all_specs),
                ["acmeextra", "acmewidget"],
            )

    def test_peer_specs_require_installer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            _write_extension(workspace, "acmewidget", policy_name="{env}-acmewidget-actions")
            specs = peer_actions_specs(["acmewidget"], workspace)
            self.assertEqual(len(specs), 1)
            self.assertEqual(
                peer_actions_policy_name("acme0813", "lab", "acmewidget"),
                "acme0813-peer-lab-acmewidget-actions",
            )
            with self.assertRaises(FileNotFoundError):
                peer_actions_specs(["missingext"], workspace)

    def test_load_spec_and_bundle_handle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = _write_extension(Path(raw), "acmewidget", policy_name="{env}-x")
            spec = load_actions_spec(folder, "acmewidget")
            self.assertIsNotNone(spec)
            assert spec is not None
            self.assertEqual(spec.document["Version"], "2012-10-17")
            bundled = Path(raw) / "extension"
            bundled.mkdir()
            (bundled / "bundle.json").write_text(
                json.dumps({"source_repo": "extensions/acmewidget"}),
                encoding="utf-8",
            )
            self.assertEqual(handle_from_extension_folder(bundled), "acmewidget")


if __name__ == "__main__":
    unittest.main()
