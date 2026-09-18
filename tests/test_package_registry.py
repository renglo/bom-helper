#!/usr/bin/env python3
"""Tests for CodeArtifact reader account resolution."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

CDK_DIR = Path(__file__).resolve().parents[1] / "cdk"
sys.path.insert(0, str(CDK_DIR))

from package_registry import codeartifact_owners, codeartifact_read_resources  # noqa: E402


class CodeArtifactOwnersTests(unittest.TestCase):
    def test_tenant_only_when_registry_omitted(self) -> None:
        self.assertEqual(codeartifact_owners("111122223333"), ["111122223333"])
        self.assertEqual(codeartifact_owners("111122223333", None), ["111122223333"])

    def test_foreign_owners_appended(self) -> None:
        self.assertEqual(
            codeartifact_owners(
                "111122223333",
                {"domain_owners": ["444455556666"]},
            ),
            ["111122223333", "444455556666"],
        )

    def test_read_resources_include_tenant_and_foreign(self) -> None:
        resources = codeartifact_read_resources(
            "us-east-1",
            "982081058012",
            {"domain_owners": ["339713094352"]},
        )
        self.assertIn(
            "arn:aws:codeartifact:us-east-1:982081058012:domain/*",
            resources,
        )
        self.assertIn(
            "arn:aws:codeartifact:us-east-1:339713094352:domain/*",
            resources,
        )


if __name__ == "__main__":
    unittest.main()
