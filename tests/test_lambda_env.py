#!/usr/bin/env python3
"""Unit tests for Lambda env filtering and 4KB size check."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from lambda_env import (  # noqa: E402
    LAMBDA_ENV_MAX_BYTES,
    assert_under_lambda_limit,
    env_payload_size,
    filter_lambda_env,
)


class LambdaEnvTests(unittest.TestCase):
    def test_drops_console_ci_and_reserved_keys(self) -> None:
        filtered = filter_lambda_env(
            {
                "WL_NAME": "acme0813",
                "VITE_WEBSOCKET_URL": "wss://example/production/",
                "AMPLIFY_APP_ID": "d123",
                "AMPLIFY_CONSOLE_URL": "https://staging.example.com",
                "CODEDEPLOY_APPLICATION_NAME": "app",
                "AWS_ECR_REPOSITORY": "repo",
                "AWS_REGION": "us-east-1",
                "LAMBDA_BACKEND_ARN": "arn:aws:lambda:...",
                "OPENAI_API_KEY": "sk-test",
                "EXTERNAL_HANDLERS_ECS_HANDLERS": "acmewidget:aws_threats;acmeextra:aws_aid_networks",
                "EXTERNAL_HANDLERS_PEER_MAP": '{"acmewidget":{"lambda_arn":"arn:..."}}',
                "bad-key": "nope",
            }
        )
        self.assertEqual(
            filtered,
            {"WL_NAME": "acme0813", "OPENAI_API_KEY": "sk-test"},
        )

    def test_payload_size_is_utf8_keys_plus_values(self) -> None:
        env = {"AB": "cd", "E": "fgh"}
        self.assertEqual(env_payload_size(env), 2 + 2 + 1 + 3)

    def test_assert_under_limit_raises_with_largest_keys(self) -> None:
        env = {"SMALL": "x", "HUGE": "y" * 80}
        with self.assertRaises(RuntimeError) as caught:
            assert_under_lambda_limit(env, limit=20)
        message = str(caught.exception)
        self.assertIn("exceeds the 20 byte limit", message)
        self.assertIn("HUGE=", message)

    def test_default_limit_matches_aws(self) -> None:
        self.assertEqual(LAMBDA_ENV_MAX_BYTES, 4096)


if __name__ == "__main__":
    unittest.main()
