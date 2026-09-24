#!/usr/bin/env python3
"""Peer deploy matrix from deploy_targets.yml."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from render_deploy_matrix import _peer_rows  # noqa: E402


class PeerMatrixTests(unittest.TestCase):
    def test_acme_multi_handle_peer_rows(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo_root = Path(raw) / "acme-bom"
            pin_dir = repo_root / "peers_bom" / "lab"
            pin_dir.mkdir(parents=True)
            (pin_dir / "v0.1.3.json").write_text(
                json.dumps({"deploy_stage": "staging", "version": "v0.1.3"}),
                encoding="utf-8",
            )
            deploy_targets = {
                "peers": {
                    "lab": {
                        "compute": "fargate",
                        "extensions": ["acmewidget", "acmeextra"],
                        "peers_bom": "0.1.3",
                    }
                },
                "tenants": {
                    "acme0813": {
                        "aws_account": "111122223333",
                        "aws_region": "us-east-1",
                        "stages": {"staging": {"enabled": True}},
                    }
                },
            }
            (repo_root / "deploy_targets.yml").write_text("peers: {}\n", encoding="utf-8")
            rows = _peer_rows(deploy_targets, repo_root)

        peers = {r["peer"] for r in rows}
        self.assertEqual(peers, {"lab"})
        lab = next(r for r in rows if r["peer"] == "lab")
        self.assertEqual(lab["function_name"], "acme0813-peer-lab")
        self.assertEqual(lab["extensions"], "acmewidget,acmeextra")
        self.assertEqual(lab["handlers_compute"], "ecs")
        self.assertEqual(lab["compute"], "fargate")
        self.assertTrue(lab["handlers_bom_file"].endswith("peers_bom/lab/v0.1.3.json"))
        self.assertIn("lab-staging", lab["oidc_role_arn"])
        self.assertEqual(lab["ssm_parameter"], "/acme0813/bootstrap/deploy-input")
        json.dumps({"include": rows})


if __name__ == "__main__":
    unittest.main()
