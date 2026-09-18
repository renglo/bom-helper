#!/usr/bin/env python3
"""Tests for prepare_handlers_wheelhouse asset extraction."""

from __future__ import annotations

import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from prepare_handlers_wheelhouse import (  # noqa: E402
    extract_assets,
    large_extra_specs,
    normalize_dist_name,
    pin_specs,
    prepare,
    version_in_wheelhouse,
)


def _write_sdist(
    dest: Path,
    dist: str,
    version: str,
    *,
    router: bool,
    config: dict | None,
    large_extra: bool = False,
) -> Path:
    """Create a minimal sdist tarball under dest."""
    # PEP 625-ish filename: name-version.tar.gz (underscores ok in archive name)
    file_name = f"{dist.replace('-', '_')}-{version}.tar.gz"
    # Actually pip uses normalized name with hyphens often; use hyphen form
    file_name = f"{dist}-{version}.tar.gz"
    archive = dest / file_name
    root_name = f"{dist}-{version}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        def _add(name: str, data: bytes) -> None:
            info = tarfile.TarInfo(name=f"{root_name}/{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

        pyproject = '[project]\nname = "x"\n'
        if large_extra:
            pyproject += (
                "[project.optional-dependencies]\n"
                'large-dependencies = ["numpy"]\n'
            )
        _add("pyproject.toml", pyproject.encode())
        if router:
            _add("lambda_router.py", b"# router\n")
        if config is not None:
            import json

            _add("handlers_config.json", json.dumps(config).encode())
    archive.write_bytes(buf.getvalue())
    return archive


class PrepareAssetsTest(unittest.TestCase):
    def test_normalize(self) -> None:
        self.assertEqual(normalize_dist_name("Acme_Widget"), "acme-widget")

    def test_extract_primary_and_extra(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            wheelhouse = root / "wheelhouse"
            assets = root / "handlers-assets"
            wheelhouse.mkdir()
            _write_sdist(
                wheelhouse,
                "acme-widget",
                "0.0.1",
                router=True,
                config={"handlers": {"a": {}}},
            )
            _write_sdist(
                wheelhouse,
                "acme-extra",
                "0.0.1",
                router=True,
                config={"handlers": {"b": {}}},
            )
            extract_assets(
                wheelhouse,
                assets,
                ["acme-widget", "acme-extra"],
            )
            self.assertTrue((assets / "lambda_router.py").is_file())
            self.assertTrue((assets / "handlers_config.json").is_file())
            extra = assets / "extras" / "acme-extra" / "handlers_config.json"
            self.assertTrue(extra.is_file())
            text = (assets / "handlers_config.json").read_text(encoding="utf-8")
            self.assertIn('"a"', text)
            self.assertIn('"b"', text)  # merged into primary for multi-package peers

    def test_large_extra_specs(self) -> None:
        self.assertEqual(
            large_extra_specs(["acme-widget", "acme-extra"]),
            [
                "acme-widget[large-dependencies]",
                "acme-extra[large-dependencies]",
            ],
        )

    def test_pin_specs_from_wheelhouse(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wheelhouse = Path(raw)
            (wheelhouse / "acme_widget-0.0.5-py3-none-any.whl").write_bytes(b"x")
            (wheelhouse / "acme_widget-0.0.4-py3-none-any.whl").write_bytes(b"x")
            self.assertEqual(version_in_wheelhouse(wheelhouse, "acme-widget"), "0.0.5")
            self.assertEqual(
                pin_specs(["acme-widget"], wheelhouse),
                ["acme-widget==0.0.5"],
            )
            self.assertEqual(
                large_extra_specs(["acme-widget"], wheelhouse),
                ["acme-widget[large-dependencies]==0.0.5"],
            )

    def test_large_extra_specs_skips_packages_without_extra(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wheelhouse = Path(raw)
            _write_sdist(
                wheelhouse,
                "renglo-lib",
                "0.0.4rc1",
                router=False,
                config=None,
            )
            _write_sdist(
                wheelhouse,
                "arbitium-lab",
                "0.0.6rc2",
                router=True,
                config={"handlers": {}},
                large_extra=True,
            )
            self.assertEqual(
                large_extra_specs(["renglo-lib", "arbitium-lab"], wheelhouse),
                ["arbitium-lab[large-dependencies]==0.0.6rc2"],
            )

    def test_prepare_with_large_deps_calls_download(self) -> None:
        import unittest.mock as mock

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            _write_sdist(
                artifacts,
                "acme-widget",
                "0.0.1",
                router=True,
                config={"handlers": {}},
                large_extra=True,
            )
            calls: list[list[str]] = []

            def fake_download(_wh, packages, **kwargs):
                calls.append(
                    (
                        list(packages),
                        kwargs.get("strict", False),
                        {
                            "extra_index_urls": kwargs.get("extra_index_urls"),
                            "wheels_only": kwargs.get("wheels_only", False),
                        },
                    )
                )

            with mock.patch(
                "prepare_handlers_wheelhouse.download_deps", side_effect=fake_download
            ):
                ordered = prepare(
                    out_dir=root / "out",
                    from_monorepo=[],
                    from_artifacts=artifacts,
                    packages=["acme-widget"],
                    skip_deps=False,
                    with_large_deps=True,
                )
            self.assertEqual(ordered, ["acme-widget"])
            self.assertEqual(
                calls[0],
                (
                    ["acme-widget==0.0.1"],
                    True,
                    {"extra_index_urls": ["https://pypi.org/simple"], "wheels_only": False},
                ),
            )
            self.assertEqual(
                calls[1],
                (
                    ["acme-widget[large-dependencies]==0.0.1"],
                    True,
                    {
                        "extra_index_urls": ["https://pypi.org/simple"],
                        "wheels_only": True,
                    },
                ),
            )


if __name__ == "__main__":
    unittest.main()
