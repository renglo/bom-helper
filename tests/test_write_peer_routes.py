#!/usr/bin/env python3
"""Tests for CloudFormation output key matching in write_peer_routes."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from write_peer_routes import (  # noqa: E402
    _output,
    _route_from_outputs,
    heavy_handlers_for_extension,
)


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
                "ComputeHandlersComputeSubnetIdsA1B2C3D4": "subnet-a,subnet-b",
                "ComputeHandlersComputeSecurityGroupIdE5F6G7H8": "sg-abc",
                "ComputeHandlersLaunchTypeI9J0K1L2": "fargate",
                "ComputeHandlersNetworkModeM3N4O5P6": "awsvpc",
            },
            "us-east-1",
            "123",
        )
        self.assertEqual(
            route["arbitiumlab"]["lambda_arn"],
            "arn:aws:lambda:us-east-1:123:function:acme0813-peer-lab",
        )
        self.assertEqual(route["arbitiumlab"]["ecs_cluster"], "acme0813-peer-lab")
        self.assertEqual(route["arbitiumlab"]["subnets"], ["subnet-a", "subnet-b"])
        self.assertEqual(route["arbitiumlab"]["security_groups"], ["sg-abc"])
        self.assertEqual(route["arbitiumlab"]["launch_type"], "fargate")
        self.assertEqual(route["arbitiumlab"]["network_mode"], "awsvpc")
        self.assertNotIn("heavy_handlers", route["arbitiumlab"])

    def test_route_embeds_heavy_handlers(self) -> None:
        route = _route_from_outputs(
            ["arbitiumlab", "arbitiumtriage"],
            {"HandlersLambdaFunctionName": "acme0813-peer-lab"},
            "us-east-1",
            "123",
            heavy_by_ext={"arbitiumlab": ["aws_threats"], "arbitiumtriage": []},
        )
        self.assertEqual(route["arbitiumlab"]["heavy_handlers"], ["aws_threats"])
        self.assertNotIn("heavy_handlers", route["arbitiumtriage"])

    def test_heavy_handlers_from_package_config(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg = root / "extensions" / "acmewidget" / "package"
            pkg.mkdir(parents=True)
            (pkg / "handlers_config.json").write_text(
                '{"heavy_handlers": ["orch", "aws_threats"]}',
                encoding="utf-8",
            )
            self.assertEqual(
                heavy_handlers_for_extension("acmewidget", [root]),
                ["orch", "aws_threats"],
            )

    def test_missing_function_name_is_empty(self) -> None:
        self.assertEqual(
            _route_from_outputs(["arbitiumlab"], {"Other": "x"}, "us-east-1", "123"),
            {},
        )


if __name__ == "__main__":
    unittest.main()
