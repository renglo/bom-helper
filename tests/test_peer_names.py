#!/usr/bin/env python3
"""Overflow vs peer resource name guards."""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
CDK = Path(__file__).resolve().parents[1] / "cdk"
sys.path.insert(0, str(SCRIPTS))

from peers import handlers_unit_name  # noqa: E402
from teardown_overflow_handlers import is_overflow_lambda, overflow_names  # noqa: E402


class NamingTests(unittest.TestCase):
    def test_overflow_vs_peer_lambda(self) -> None:
        env = "acme0813"
        self.assertTrue(is_overflow_lambda(env, "acme0813-handlers"))
        self.assertFalse(is_overflow_lambda(env, "acme0813-peer-lab"))
        self.assertFalse(is_overflow_lambda(env, "acme0813-peer-triage"))
        names = overflow_names(env, "123")
        self.assertEqual(names["lambda"], "acme0813-handlers")
        self.assertEqual(names["cluster"], "acme0813-handlers")
        self.assertEqual(handlers_unit_name(env, "lab"), "acme0813-peer-lab")
        self.assertNotEqual(names["lambda"], handlers_unit_name(env, "lab"))

    def test_compute_stack_parses(self) -> None:
        src = (CDK / "compute_stack.py").read_text(encoding="utf-8")
        ast.parse(src)
        app = (CDK / "app.py").read_text(encoding="utf-8")
        ast.parse(app)
        self.assertIn("peer_id", src)
        self.assertIn("handlers_unit_name", src)


if __name__ == "__main__":
    unittest.main()
