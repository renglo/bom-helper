#!/usr/bin/env python3
"""Peer CDK deploy_targets.yml resolution tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CDK_DIR = Path(__file__).resolve().parents[1] / "cdk"
sys.path.insert(0, str(CDK_DIR))

import targets  # noqa: E402


class ResolveTargetsTests(unittest.TestCase):
    def test_explicit_context_wins(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            targets_file = root / "custom" / "deploy_targets.yml"
            targets_file.parent.mkdir(parents=True)
            targets_file.write_text("peers: {}\n", encoding="utf-8")
            fake_app = mock.Mock()
            fake_app.node.try_get_context.return_value = str(targets_file)
            resolved = targets.resolve_targets_path(
                fake_app,
                helper_root=root / "bom-helper",
                tenant_key="acme",
                bom_checkout="",
            )
            self.assertTrue(resolved.samefile(targets_file))

    def test_sibling_tenant_bom(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            helper = root / "bom-helper"
            bom = root / "acme-bom"
            helper.mkdir()
            bom.mkdir()
            targets_file = bom / "deploy_targets.yml"
            targets_file.write_text("peers: {}\n", encoding="utf-8")
            fake_app = mock.Mock()
            fake_app.node.try_get_context.return_value = None
            with mock.patch.dict("os.environ", {}, clear=True):
                resolved = targets.resolve_targets_path(
                    fake_app,
                    helper_root=helper,
                    tenant_key="acme",
                    bom_checkout="",
                )
            self.assertEqual(resolved, targets_file.resolve())

    def test_bom_checkout_override(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            helper = root / "bom-helper"
            bom = root / "custom-bom-name"
            helper.mkdir()
            bom.mkdir()
            targets_file = bom / "deploy_targets.yml"
            targets_file.write_text("peers: {}\n", encoding="utf-8")
            fake_app = mock.Mock()
            fake_app.node.try_get_context.return_value = None
            with mock.patch.dict("os.environ", {}, clear=True):
                resolved = targets.resolve_targets_path(
                    fake_app,
                    helper_root=helper,
                    tenant_key="acme",
                    bom_checkout="custom-bom-name",
                )
            self.assertEqual(resolved, targets_file.resolve())


if __name__ == "__main__":
    unittest.main()
