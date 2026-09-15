#!/usr/bin/env python3
"""Tests for prepare_handlers_wheelhouse asset extraction."""

from __future__ import annotations

import io
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from prepare_handlers_wheelhouse import (  # noqa: E402
    dist_provides_extra,
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
    file_name = f"{dist}-{version}.tar.gz"
    archive = dest / file_name
    root_name = f"{dist}-{version}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        def _add(name: str, data: bytes) -> None:
            info = tarfile.TarInfo(name=f"{root_name}/{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

        pyproject = f'[project]\nname = "{dist}"\n'
        if large_extra:
            pyproject += (
                "[project.optional-dependencies]\n"
                "large-dependencies = [\"numpy>=1.0\"]\n"
            )
        _add("pyproject.toml", pyproject.encode())
        if router:
            _add("lambda_router.py", b"# router\n")
        if config is not None:
            import json

            _add("handlers_config.json", json.dumps(config).encode())
    archive.write_bytes(buf.getvalue())
    return archive


def _write_wheel(
    dest: Path,
    dist: str,
    version: str,
    *,
    provides_large: bool = False,
) -> Path:
    """Minimal wheel with METADATA (and optional Provides-Extra)."""
    # Wheel filename uses underscores in the name segment.
    whl_name = f"{dist.replace('-', '_')}-{version}-py3-none-any.whl"
    path = dest / whl_name
    dist_info = f"{dist.replace('-', '_')}-{version}.dist-info"
    meta = (
        f"Metadata-Version: 2.1\n"
        f"Name: {dist}\n"
        f"Version: {version}\n"
    )
    if provides_large:
        meta += "Provides-Extra: large-dependencies\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{dist_info}/METADATA", meta)
        zf.writestr(f"{dist_info}/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\n")
    path.write_bytes(buf.getvalue())
    return path


class PrepareAssetsTest(unittest.TestCase):
    def test_normalize(self) -> None:
        self.assertEqual(normalize_dist_name("Arbitium_Lab"), "arbitium-lab")

    def test_extract_primary_and_extra(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            wheelhouse = root / "wheelhouse"
            assets = root / "handlers-assets"
            wheelhouse.mkdir()
            _write_sdist(
                wheelhouse,
                "arbitium-lab",
                "0.0.1",
                router=True,
                config={"handlers": {"a": {}}},
            )
            _write_sdist(
                wheelhouse,
                "arbitium-triage",
                "0.0.1",
                router=True,
                config={"handlers": {"b": {}}},
            )
            extract_assets(
                wheelhouse,
                assets,
                ["arbitium-lab", "arbitium-triage"],
            )
            self.assertTrue((assets / "lambda_router.py").is_file())
            self.assertTrue((assets / "handlers_config.json").is_file())
            extra = assets / "extras" / "arbitium-triage" / "handlers_config.json"
            self.assertTrue(extra.is_file())
            text = (assets / "handlers_config.json").read_text(encoding="utf-8")
            self.assertIn('"a"', text)
            self.assertNotIn('"b"', text)  # extra stays under extras/

    def test_large_extra_specs_requires_metadata(self) -> None:
        self.assertEqual(
            large_extra_specs(["arbitium-lab", "arbitium-triage"]),
            [],
        )

    def test_large_extra_specs_from_wheel_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wheelhouse = Path(raw)
            _write_wheel(
                wheelhouse, "arbitium-lab", "0.0.5", provides_large=True
            )
            _write_wheel(
                wheelhouse, "arbitium-triage", "0.0.5", provides_large=False
            )
            _write_wheel(wheelhouse, "renglo-lib", "0.0.4", provides_large=False)
            self.assertTrue(dist_provides_extra(wheelhouse, "arbitium-lab"))
            self.assertFalse(dist_provides_extra(wheelhouse, "arbitium-triage"))
            self.assertEqual(
                large_extra_specs(
                    ["renglo-lib", "arbitium-lab", "arbitium-triage"],
                    wheelhouse,
                ),
                ["arbitium-lab[large-dependencies]==0.0.5"],
            )

    def test_large_extra_specs_from_sdist_pyproject(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wheelhouse = Path(raw)
            _write_sdist(
                wheelhouse,
                "arbitium-lab",
                "0.0.1",
                router=False,
                config=None,
                large_extra=True,
            )
            _write_sdist(
                wheelhouse,
                "arbitium-triage",
                "0.0.1",
                router=False,
                config=None,
                large_extra=False,
            )
            self.assertEqual(
                large_extra_specs(
                    ["arbitium-lab", "arbitium-triage"], wheelhouse
                ),
                ["arbitium-lab[large-dependencies]==0.0.1"],
            )

    def test_pin_specs_from_wheelhouse(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wheelhouse = Path(raw)
            _write_wheel(
                wheelhouse, "arbitium-lab", "0.0.5", provides_large=True
            )
            _write_wheel(
                wheelhouse, "arbitium-lab", "0.0.4", provides_large=True
            )
            self.assertEqual(version_in_wheelhouse(wheelhouse, "arbitium-lab"), "0.0.5")
            self.assertEqual(
                pin_specs(["arbitium-lab"], wheelhouse),
                ["arbitium-lab==0.0.5"],
            )
            self.assertEqual(
                large_extra_specs(["arbitium-lab"], wheelhouse),
                ["arbitium-lab[large-dependencies]==0.0.5"],
            )

    def test_prepare_with_large_deps_calls_download(self) -> None:
        import unittest.mock as mock

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            _write_sdist(
                artifacts,
                "arbitium-lab",
                "0.0.1",
                router=True,
                config={"handlers": {}},
                large_extra=True,
            )
            _write_sdist(
                artifacts,
                "arbitium-triage",
                "0.0.1",
                router=False,
                config=None,
                large_extra=False,
            )
            calls: list[tuple] = []

            def fake_download(_wh, packages, **kwargs):
                calls.append(
                    (
                        list(packages),
                        kwargs.get("strict", False),
                        kwargs.get("extra_index_urls"),
                    )
                )

            with mock.patch(
                "prepare_handlers_wheelhouse.download_deps", side_effect=fake_download
            ):
                ordered = prepare(
                    out_dir=root / "out",
                    from_monorepo=[],
                    from_artifacts=artifacts,
                    packages=["arbitium-lab", "arbitium-triage"],
                    skip_deps=False,
                    with_large_deps=True,
                )
            self.assertEqual(ordered, ["arbitium-lab", "arbitium-triage"])
            pypi = ["https://pypi.org/simple"]
            self.assertEqual(
                calls[0],
                (["arbitium-lab==0.0.1", "arbitium-triage==0.0.1"], True, pypi),
            )
            self.assertEqual(
                calls[1],
                (["arbitium-lab[large-dependencies]==0.0.1"], True, pypi),
            )


if __name__ == "__main__":
    unittest.main()
