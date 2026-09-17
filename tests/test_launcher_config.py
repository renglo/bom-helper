#!/usr/bin/env python3
"""Launcher + peer deploy context resolution tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

CDK_DIR = Path(__file__).resolve().parents[1] / "cdk"
sys.path.insert(0, str(CDK_DIR))

import launcher_config  # noqa: E402
from peer_deploy_context import resolve_peer_deploy_context  # noqa: E402


class LauncherConfigTests(unittest.TestCase):
    def test_checkout_name_from_github_repo(self) -> None:
        self.assertEqual(
            launcher_config.github_repo_checkout_name("Org/acme-bom"),
            "acme-bom",
        )

    def test_resolve_from_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            helper = root / "bom-helper"
            launcher = root / "launcher" / "cdk"
            launcher.mkdir(parents=True)
            (launcher / "customer-config.json").write_text(
                json.dumps(
                    {
                        "env_name": "acme0813",
                        "github_repo": "Org/acme-bom",
                    }
                ),
                encoding="utf-8",
            )
            resolved = launcher_config.resolve_from_launcher(helper)
            self.assertEqual(resolved["env_name"], "acme0813")
            self.assertEqual(resolved["bom_repo"], "Org/acme-bom")
            self.assertEqual(resolved["bom_checkout"], "acme-bom")


class PeerDeployContextTests(unittest.TestCase):
    def test_monorepo_auto_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            helper = root / "bom-helper"
            bom = root / "acme-bom"
            launcher = root / "launcher" / "cdk"
            helper.mkdir()
            bom.mkdir()
            launcher.mkdir(parents=True)
            (launcher / "customer-config.json").write_text(
                json.dumps({"env_name": "acme0813", "github_repo": "Org/acme-bom"}),
                encoding="utf-8",
            )
            (bom / "deploy_targets.yml").write_text(
                "peers:\n  analytics:\n    compute: lambda_only\n"
                "    extensions: [ledger]\n    peers_bom: 0.0.1\n"
                "tenants:\n  acme:\n    id: acme0813\n",
                encoding="utf-8",
            )
            ctx = resolve_peer_deploy_context(helper_root=helper)
            self.assertEqual(ctx["tenant"], "acme")
            self.assertEqual(ctx["env_name"], "acme0813")
            self.assertEqual(ctx["bom_repo"], "Org/acme-bom")
            self.assertTrue(ctx["targets_path"].endswith("acme-bom/deploy_targets.yml"))


if __name__ == "__main__":
    unittest.main()
