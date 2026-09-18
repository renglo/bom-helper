#!/usr/bin/env python3
"""Tests for CloudFormation output key matching in write_peer_routes."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from write_peer_routes import _output, _route_from_outputs  # noqa: E402


class CfnOutputMatchTests(unittest.TestCase):
    def test_exact_logical_id(self) -> None:
        self.assertEqual(
            _output({"HandlersLambdaFunctionName": "acme0813-peer-lab"}, "HandlersLambdaFunctionName"),
            "acme0813-peer-lab",
        )

    def test_cdk_hashed_nested_id(self) -> None:
        self.assertEqual(
            _output(
                {"ComputeHandlersLambdaFunctionName3250848C": "acme0813-peer-lab"},
                "HandlersLambdaFunctionName",
            ),
            "acme0813-peer-lab",
        )

    def test_route_from_hashed_outputs(self) -> None:
        route = _route_from_outputs(
            ["arbitiumlab"],
            {
                "ComputeHandlersLambdaFunctionName3250848C": "acme0813-peer-lab",
                "ComputeHandlersEcsClusterName32CDBAD3": "acme0813-peer-lab",
                "ComputeHandlersTaskFamilyD73E0C2C": "acme0813-peer-lab-ecs",
                "ComputeHandlersResultsBucketNameB7647493": "bucket",
            },
            "us-east-1",
            "123",
        )
        self.assertEqual(
            route["arbitiumlab"]["lambda_arn"],
            "arn:aws:lambda:us-east-1:123:function:acme0813-peer-lab",
        )
        self.assertEqual(route["arbitiumlab"]["ecs_cluster"], "acme0813-peer-lab")

    def test_missing_function_name_is_empty(self) -> None:
        self.assertEqual(
            _route_from_outputs(["arbitiumlab"], {"Other": "x"}, "us-east-1", "123"),
            {},
        )


if __name__ == "__main__":
    unittest.main()
