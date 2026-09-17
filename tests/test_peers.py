#!/usr/bin/env python3
"""Peer catalog schema tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from peers import (  # noqa: E402
    apply_external_handlers_from_peers,
    external_handlers_csv,
    handlers_unit_name,
    load_peers,
    oidc_handlers_role_name,
    parse_peer,
    peer_for_handle,
    peer_stack_name,
)


def _acme_peer_catalog(**lab_over: object) -> dict:
    lab = {
        "compute": "fargate",
        "extensions": ["acmewidget", "acmeextra"],
        "peers_bom": "0.1.3",
    }
    lab.update(lab_over)
    return {
        "handlers_bom": "0.1.3",
        "peers": {
            "lab": lab,
        },
    }


class PeerCatalogTests(unittest.TestCase):
    def test_load_lab_triage(self) -> None:
        peers = load_peers(_acme_peer_catalog())
        self.assertEqual([p["id"] for p in peers], ["lab"])
        self.assertEqual(external_handlers_csv(peers), "acmewidget,acmeextra")
        self.assertEqual(peer_for_handle(peers, "acmewidget")["id"], "lab")
        self.assertEqual(peer_for_handle(peers, "acmeextra")["id"], "lab")
        self.assertEqual(peer_for_handle(peers, "acmewidget")["bom_path"], "peers_bom/lab")
        self.assertEqual(peer_for_handle(peers, "acmeextra")["bom_path"], "peers_bom/lab")
        self.assertIsNone(peer_for_handle(peers, "unknown"))

    def test_unit_and_stack_names(self) -> None:
        self.assertEqual(handlers_unit_name("acme0813"), "acme0813-handlers")
        self.assertEqual(handlers_unit_name("acme0813", "lab"), "acme0813-peer-lab")
        self.assertEqual(peer_stack_name("acme0813", "lab"), "acme0813-peer-lab")
        self.assertEqual(
            oidc_handlers_role_name("acme0813", "staging"),
            "GitHubActionsHandlersRole-acme0813-staging",
        )
        self.assertEqual(
            oidc_handlers_role_name("acme0813", "staging", "lab"),
            "GitHubActionsHandlersRole-acme0813-lab-staging",
        )

    def test_duplicate_handle_rejected(self) -> None:
        data = _acme_peer_catalog()
        data["peers"]["accounting"] = {
            "compute": "lambda_only",
            "extensions": ["acmewidget"],
            "peers_bom": "0.0.1",
        }
        with self.assertRaisesRegex(RuntimeError, "acmewidget"):
            load_peers(data)

    def test_lambda_only_and_ec2(self) -> None:
        only = parse_peer(
            "ledger",
            {
                "compute": "lambda_only",
                "extensions": ["ledger"],
                "handlers_bom": "0.0.1",
            },
        )
        self.assertEqual(only["compute"], "lambda_only")
        self.assertEqual(only["bom_path"], "peers_bom/ledger")
        self.assertEqual(only["peers_bom"], "0.0.1")
        ec2 = parse_peer(
            "heavy",
            {
                "compute": "ec2",
                "extensions": ["train"],
                "handlers_bom": "0.0.1",
                "ec2_instance_type": "m5.large",
                "ec2_min_instances": 0,
                "ec2_desired_instances": 1,
                "ec2_max_instances": 2,
            },
        )
        self.assertEqual(ec2["ec2_instance_type"], "m5.large")
        with self.assertRaisesRegex(RuntimeError, "ec2_instance_type"):
            parse_peer(
                "heavy",
                {
                    "compute": "ec2",
                    "extensions": ["train"],
                    "handlers_bom": "0.0.1",
                    "ec2_min_instances": 0,
                    "ec2_desired_instances": 1,
                    "ec2_max_instances": 2,
                },
            )

    def test_empty_catalog(self) -> None:
        self.assertEqual(load_peers({}), [])
        vars_block = {"EXTERNAL_HANDLERS": "keep-me"}
        apply_external_handlers_from_peers(vars_block, [])
        self.assertEqual(vars_block["EXTERNAL_HANDLERS"], "keep-me")
        apply_external_handlers_from_peers(vars_block, load_peers(_acme_peer_catalog()))
        self.assertEqual(vars_block["EXTERNAL_HANDLERS"], "acmewidget,acmeextra")

    def test_handlers_bom_alias_still_parses(self) -> None:
        peer = parse_peer(
            "lab",
            {
                "compute": "fargate",
                "extensions": ["acmewidget"],
                "handlers_bom": "0.1.3",
                "bom_path": "handlers_bom/lab",
            },
        )
        self.assertEqual(peer["peers_bom"], "0.1.3")
        self.assertEqual(peer["bom_path"], "handlers_bom/lab")

    def test_invalid_compute(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "compute"):
            parse_peer("lab", {"compute": "cluster", "extensions": ["a"], "handlers_bom": "1.0.0"})


if __name__ == "__main__":
    unittest.main()
