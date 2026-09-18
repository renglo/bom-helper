#!/usr/bin/env python3
"""Tests for peer_packager publish handler pinning and runtime env."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from peer_packager import LAMBDA_HANDLER, cmd_publish  # noqa: E402


class PublishHandlerTests(unittest.TestCase):
    def test_publish_sets_lambda_router_handler_and_tables(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            zip_path = Path(raw) / "lambda_deployment.zip"
            zip_path.write_bytes(b"zip")
            extra = Path(raw) / "lambda_env_merge.json"
            extra.write_text(
                json.dumps(
                    {
                        "OPENAI_API_KEY": "sk-test",
                        "LAMBDA_FUNCTION_NAME": "acme0813-handlers",
                        "DYNAMODB_ENTITY_TABLE": "wrong_entities",
                    }
                ),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                env_name="acme0813",
                peer_id="lab",
                zip=str(zip_path),
                region="us-east-1",
                env_json=str(extra),
            )
            calls: list[list[str]] = []
            payloads: list[dict] = []

            def fake_run(cmd, check=True, cwd=None, env=None):  # noqa: ARG001
                calls.append(list(cmd))
                if "--cli-input-json" in cmd:
                    flag = cmd[cmd.index("--cli-input-json") + 1]
                    payloads.append(
                        json.loads(Path(flag.removeprefix("file://")).read_text(encoding="utf-8"))
                    )

            with mock.patch("peer_packager._run", side_effect=fake_run):
                self.assertEqual(cmd_publish(args), 0)

        self.assertEqual(calls[0][1:3], ["lambda", "update-function-code"])
        self.assertEqual(calls[1][1:4], ["lambda", "wait", "function-updated"])
        self.assertEqual(calls[2][1:3], ["lambda", "update-function-configuration"])
        self.assertEqual(calls[3][1:4], ["lambda", "wait", "function-updated"])
        self.assertEqual(LAMBDA_HANDLER, "lambda_router.lambda_handler")
        self.assertEqual(len(payloads), 1)
        cfg = payloads[0]
        self.assertEqual(cfg["FunctionName"], "acme0813-peer-lab")
        self.assertEqual(cfg["Handler"], LAMBDA_HANDLER)
        env = cfg["Environment"]["Variables"]
        self.assertEqual(env["WL_NAME"], "acme0813")
        self.assertEqual(env["DYNAMODB_ENTITY_TABLE"], "acme0813_entities")
        self.assertEqual(env["DYNAMODB_RINGDATA_TABLE"], "acme0813_data")
        self.assertEqual(env["OPENAI_API_KEY"], "sk-test")
        self.assertNotIn("LAMBDA_FUNCTION_NAME", env)


if __name__ == "__main__":
    unittest.main()
