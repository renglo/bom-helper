#!/usr/bin/env python3
"""Tests for multi-publisher CodeArtifact registry resolution."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from registry_targets import (  # noqa: E402
    DEFAULT_REGISTRY,
    resolve_registries,
    resolve_registry,
)
from configure_codeartifact import pip_extra_index_url  # noqa: E402


def _base(**overrides):
    data = {
        "tenants": {
            "example": {
                "id": "acme",
                "aws_account": "111122223333",
                "aws_region": "us-east-1",
                "stages": {"staging": {"enabled": True}},
            }
        }
    }
    data.update(overrides)
    return data


class ResolveRegistriesTests(unittest.TestCase):
    def test_omitted_registries_returns_internal_default(self) -> None:
        regs = resolve_registries(_base())
        self.assertEqual(len(regs), 1)
        self.assertEqual(regs[0]["domain_owner"], "111122223333")
        self.assertEqual(regs[0]["domain"], DEFAULT_REGISTRY["domain"])
        self.assertEqual(regs[0]["region"], "us-east-1")
        self.assertEqual(regs[0]["npm_scopes"], [])

    def test_empty_registries_returns_internal_default(self) -> None:
        regs = resolve_registries(_base(registries=[]))
        self.assertEqual(len(regs), 1)
        self.assertEqual(regs[0]["domain_owner"], "111122223333")

    def test_rejects_singular_registry(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "registries"):
            resolve_registries(_base(registry={"domain": "x"}))

    def test_foreign_only_prepends_internal(self) -> None:
        regs = resolve_registries(
            _base(
                registries=[
                    {
                        "domain": "contoso",
                        "domain_owner": "444455556666",
                        "npm_scopes": ["@contoso"],
                    }
                ]
            )
        )
        self.assertEqual(len(regs), 2)
        self.assertEqual(regs[0]["domain_owner"], "111122223333")
        self.assertEqual(regs[1]["domain"], "contoso")
        self.assertEqual(regs[1]["npm_scopes"], ["@contoso"])

    def test_declared_internal_plus_foreign_no_double(self) -> None:
        regs = resolve_registries(
            _base(
                registries=[
                    {
                        "domain": "arbitium",
                        "npm_scopes": ["@arbitium"],
                    },
                    {
                        "domain": "renglo",
                        "domain_owner": "339713094352",
                        "npm_scopes": ["@renglo"],
                    },
                ]
            )
        )
        self.assertEqual(len(regs), 2)
        self.assertEqual(regs[0]["domain"], "arbitium")
        self.assertEqual(regs[0]["domain_owner"], "111122223333")
        self.assertEqual(regs[1]["domain"], "renglo")

    def test_many_foreign(self) -> None:
        regs = resolve_registries(
            _base(
                registries=[
                    {"domain": "a", "domain_owner": "1", "npm_scopes": ["@a"]},
                    {"domain": "b", "domain_owner": "2", "npm_scopes": ["@b"]},
                    {"domain": "c", "domain_owner": "3", "npm_scopes": ["@c"]},
                ]
            )
        )
        self.assertEqual(len(regs), 4)
        self.assertEqual([r["domain"] for r in regs], [DEFAULT_REGISTRY["domain"], "a", "b", "c"])

    def test_env_overrides_apply_to_first(self) -> None:
        regs = resolve_registries(
            _base(registries=[]),
            domain_override="custom",
            owner_override="999988887777",
        )
        self.assertEqual(regs[0]["domain"], "custom")
        self.assertEqual(regs[0]["domain_owner"], "999988887777")

    def test_resolve_registry_is_first(self) -> None:
        first = resolve_registry(
            _base(
                registries=[
                    {"domain": "arbitium"},
                    {"domain": "renglo", "domain_owner": "339713094352"},
                ]
            )
        )
        self.assertEqual(first["domain"], "arbitium")


class ConfigureCodeartifactHelpersTests(unittest.TestCase):
    def test_pip_extra_index_url(self) -> None:
        url = pip_extra_index_url(
            "https://domain-111.d.codeartifact.us-east-1.amazonaws.com/pypi/python-store/",
            "tok/en+value",
        )
        self.assertTrue(url.startswith("https://aws:"))
        self.assertIn("@domain-111.d.codeartifact.us-east-1.amazonaws.com/pypi/python-store/simple/", url)
        self.assertIn("tok%2Fen%2Bvalue", url)


if __name__ == "__main__":
    unittest.main()
