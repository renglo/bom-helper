#!/usr/bin/env python3
"""extensions CLI: catalog edits, pin bump, install sheet."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HELPER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HELPER))
sys.path.insert(0, str(HELPER / "scripts"))

from extensions_cli.catalog_edit import (  # noqa: E402
    add_hub_python,
    add_new_peer,
    add_peer_extension,
    add_peer_python,
    ensure_package_slot,
    set_version_pointer,
)
from extensions_cli.cli import main  # noqa: E402
from extensions_cli.pin import bump_patch  # noqa: E402
from extensions_cli import commands  # noqa: E402
from extensions_cli.state import save  # noqa: E402


TARGETS = """# catalog
bom: 0.1.8
console_bom: 0.1.8
hub:
  python:
    - renglo-data
packages:
  data:
    python: renglo-data
peers:
  lab:
    compute: fargate
    extensions: [arbitiumlab]
    python:
      - arbitium-lab
    peers_bom: 0.1.8
tenants:
  acme:
    id: acme0813
"""


def _workspace(tmp: Path) -> Path:
    ws = tmp / "ws"
    (ws / "extensions" / "xyz" / "installer" / "infra").mkdir(parents=True)
    (ws / "extensions" / "xyz" / "installer" / "infra" / "cdk_extension.json").write_text(
        json.dumps({"policy_file": "actions_tt_policy.json", "policy_name": "{env}-xyz-actions"}),
        encoding="utf-8",
    )
    (ws / "extensions" / "xyz" / "installer" / "infra" / "actions_tt_policy.json").write_text(
        json.dumps({"Version": "2012-10-17", "Statement": []}),
        encoding="utf-8",
    )
    (ws / "extensions" / "xyz" / "package").mkdir(parents=True)
    (ws / "extensions" / "xyz" / "package" / "pyproject.toml").write_text(
        '[project]\nname = "xyz"\nversion = "0.0.1"\n',
        encoding="utf-8",
    )
    bom = ws / "ops" / "acme-bom"
    (bom / "bom").mkdir(parents=True)
    (bom / "peers_bom" / "lab").mkdir(parents=True)
    (bom / "deploy_targets.yml").write_text(TARGETS, encoding="utf-8")
    pin = {
        "version": "v0.1.8",
        "python": {"renglo-lib": "0.0.5", "arbitium-wl": "0.0.3", "arbitium-lab": "0.0.7"},
        "repos": {},
    }
    (bom / "bom" / "v0.1.8.json").write_text(json.dumps(pin), encoding="utf-8")
    (bom / "peers_bom" / "lab" / "v0.1.8.json").write_text(json.dumps(pin), encoding="utf-8")
    launch = ws / "ops" / "launcher" / "cdk"
    launch.mkdir(parents=True)
    (launch / "customer-config.json").write_text(
        json.dumps(
            {
                "env_name": "acme0813",
                "github_repo": "Acme/acme-bom",
                "aws_region": "us-east-1",
            }
        ),
        encoding="utf-8",
    )
    return ws


class CatalogEditTests(unittest.TestCase):
    def test_package_hub_peer_and_new_peer(self) -> None:
        text = ensure_package_slot(TARGETS, "xyz", "xyz")
        self.assertIn("  xyz:\n    python: xyz\n", text)
        text = add_hub_python(text, "xyz")
        self.assertIn("- xyz", text.split("hub:")[1].split("packages:")[0])
        text = add_peer_extension(TARGETS, "lab", "xyz")
        self.assertIn("extensions: [arbitiumlab, xyz]", text)
        text = add_peer_python(TARGETS, "lab", "xyz")
        self.assertIn("- xyz", text.split("peers:")[1])
        text = add_new_peer(
            TARGETS,
            peer_id="audio",
            handle="xyz",
            dist="xyz",
            compute="fargate",
            task_size="medium",
            peers_bom="0.1.8",
        )
        self.assertIn("  audio:", text)
        self.assertIn("extensions: [xyz]", text)
        self.assertLess(text.index("  audio:"), text.index("tenants:"))

    def test_pointer_bump(self) -> None:
        text = set_version_pointer(TARGETS, "peers_bom", "0.1.9", peer_id="lab")
        self.assertIn("peers_bom: 0.1.9", text)
        self.assertEqual(bump_patch("0.1.8"), "0.1.9")


class InstallFlowTests(unittest.TestCase):
    def test_place_config_pin_test_finish(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ws = _workspace(Path(raw))
            placed = commands.place(
                ws,
                "xyz",
                hub=False,
                peer="lab",
                new_peer="",
                compute="fargate",
                task_size="medium",
                python_version="0.0.1",
                npm="",
                aws_profile="acme-test",
                aws_region="us-east-1",
            )
            self.assertEqual(placed["sheet"]["phase"], "placed")
            self.assertEqual(placed["sheet"]["aws_profile"], "acme-test")
            self.assertEqual(
                (ws / "extensions" / "xyz" / "gitconvoy.toml").read_text(),
                '# git-convoy membership marker (repo root).\n'
                "# role: product | aux | bom | incubating\n"
                'role = "incubating"\n',
            )
            cfg = commands.config(ws)
            catalog = (ws / "ops" / "acme-bom" / "deploy_targets.yml").read_text()
            self.assertIn("extensions: [arbitiumlab, xyz]", catalog)
            self.assertIn("- xyz", catalog)
            self.assertEqual(cfg["sheet"]["phase"], "configured")
            pinned = commands.pin(ws, "0.0.1", "")
            self.assertEqual(pinned["pin"]["to"], "0.1.9")
            self.assertTrue((ws / "ops" / "acme-bom" / "peers_bom" / "lab" / "v0.1.9.json").is_file())
            lab = json.loads(
                (ws / "ops" / "acme-bom" / "peers_bom" / "lab" / "v0.1.9.json").read_text()
            )
            self.assertEqual(lab["python"]["xyz"], "0.0.1")
            catalog = (ws / "ops" / "acme-bom" / "deploy_targets.yml").read_text()
            self.assertIn("peers_bom: 0.1.9", catalog)
            tested = commands.test(ws, skip_synth=True)
            self.assertTrue(tested["ok"])
            self.assertEqual(tested["checks"]["unique_owner"], "peer:lab")
            save(
                ws,
                {
                    **commands.status(ws)["sheet"],
                    "phase": "pushed",
                    "test": {"ok": True},
                },
            )
            finished = commands.finish(ws)
            self.assertEqual(finished["role"], "product")
            self.assertIsNone(commands.status(ws).get("sheet"))
            self.assertIn('role = "product"', (ws / "extensions" / "xyz" / "gitconvoy.toml").read_text())

    def test_place_requires_profile(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ws = _workspace(Path(raw))
            with self.assertRaises(Exception) as ctx:
                commands.place(
                    ws,
                    "xyz",
                    hub=True,
                    peer="",
                    new_peer="",
                    compute="fargate",
                    task_size="medium",
                    python_version="",
                    npm="",
                    aws_profile="",
                )
            self.assertIn("--profile", str(ctx.exception))

    def test_place_refuses_existing_catalog_handle(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ws = _workspace(Path(raw))
            (ws / "extensions" / "arbitiumlab" / "installer" / "infra").mkdir(parents=True)
            (ws / "extensions" / "arbitiumlab" / "installer" / "infra" / "cdk_extension.json").write_text(
                json.dumps({"policy_file": "actions_tt_policy.json"}),
                encoding="utf-8",
            )
            (ws / "extensions" / "arbitiumlab" / "installer" / "infra" / "actions_tt_policy.json").write_text(
                "{}",
                encoding="utf-8",
            )
            with self.assertRaises(Exception) as ctx:
                commands.place(
                    ws,
                    "arbitiumlab",
                    hub=False,
                    peer="lab",
                    new_peer="",
                    compute="fargate",
                    task_size="medium",
                    python_version="",
                    npm="",
                    aws_profile="acme-test",
                )
            self.assertIn("already in the catalog", str(ctx.exception))

    def test_help_and_cli_help(self) -> None:
        self.assertEqual(main(["help"]), 0)


if __name__ == "__main__":
    unittest.main()
