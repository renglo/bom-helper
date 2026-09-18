#!/usr/bin/env python3
"""Tests for peer_packager publish handler pinning."""

from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from peer_packager import LAMBDA_HANDLER, cmd_publish  # noqa: E402


class PublishHandlerTests(unittest.TestCase):
    def test_publish_sets_lambda_router_handler(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            zip_path = Path(raw) / "lambda_deployment.zip"
            zip_path.write_bytes(b"zip")
            args = argparse.Namespace(
                env_name="acme0813",
                peer_id="lab",
                zip=str(zip_path),
                region="us-east-1",
            )
            calls: list[list[str]] = []

            def fake_run(cmd, check=True, cwd=None, env=None):  # noqa: ARG001
                calls.append(list(cmd))

            with mock.patch("peer_packager._run", side_effect=fake_run):
                self.assertEqual(cmd_publish(args), 0)

        self.assertEqual(calls[0][1:3], ["lambda", "update-function-code"])
        self.assertEqual(calls[1][1:4], ["lambda", "wait", "function-updated"])
        self.assertEqual(calls[2][1:3], ["lambda", "update-function-configuration"])
        self.assertIn("--handler", calls[2])
        self.assertEqual(calls[2][calls[2].index("--handler") + 1], LAMBDA_HANDLER)
        self.assertEqual(LAMBDA_HANDLER, "lambda_router.lambda_handler")


if __name__ == "__main__":
    unittest.main()
