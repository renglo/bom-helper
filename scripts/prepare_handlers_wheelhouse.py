#!/usr/bin/env python3
"""Build a handlers wheelhouse + thin assets tree for extensions-service Lambda builds.

Produces::

    <out>/wheelhouse/            # .whl / .tar.gz (find-links)
    <out>/handlers-assets/
      lambda_router.py           # from primary sdist (first package that has one)
      handlers_config.json
      extras/<dist>/handlers_config.json

Local monorepo::

    python scripts/prepare_handlers_wheelhouse.py \\
      --from-monorepo extensions/arbitium/package,extensions/arbitiumtriage/package \\
      --out .handlers-build

Pre-downloaded artifacts (CI)::

    python scripts/prepare_handlers_wheelhouse.py \\
      --from-artifacts /tmp/wheels \\
      --packages arbitium-lab,arbitium-triage \\
      --out .handlers-build
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from stage_extension_blueprints import stage_extension_blueprints

_SDIST_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.+-]+)-(?P<version>[0-9][^/]*)\.(?:tar\.gz|zip)$",
    re.IGNORECASE,
)


def normalize_dist_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def read_project_name(package_dir: Path) -> str:
    pyproject = package_dir / "pyproject.toml"
    if not pyproject.is_file():
        raise FileNotFoundError(f"pyproject.toml not found under {package_dir}")
    with pyproject.open("rb") as handle:
        data = tomllib.load(handle)
    name = str((data.get("project") or {}).get("name") or "").strip()
    if not name:
        raise ValueError(f"project.name missing in {pyproject}")
    return name


def _artifact_matches(path: Path, want_norm: str) -> bool:
    if path.name.endswith((".tar.gz", ".zip")):
        m = _SDIST_RE.match(path.name)
        return bool(m and normalize_dist_name(m.group("name")) == want_norm)
    if path.suffix == ".whl":
        stem = path.name[: -len(".whl")]
        parts = stem.split("-")
        return len(parts) >= 2 and normalize_dist_name(parts[0]) == want_norm
    return False


def _find_artifacts(wheels_dir: Path, dist_name: str) -> list[Path]:
    want = normalize_dist_name(dist_name)
    found = [p for p in sorted(wheels_dir.iterdir()) if p.is_file() and _artifact_matches(p, want)]
    return found


def _unpack_sdist_root(archive: Path, dest: Path) -> Path:
    """Unpack sdist into dest; return the single top-level project directory."""
    dest.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(dest, filter="data")
    elif archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    else:
        raise RuntimeError(f"unsupported sdist: {archive}")
    roots = [p for p in dest.iterdir() if p.is_dir()]
    if len(roots) != 1:
        raise RuntimeError(f"{archive.name}: expected one top-level directory, got {len(roots)}")
    return roots[0]


def _build_local_package(package_dir: Path, wheelhouse: Path) -> str:
    """Stage blueprints in a temp tree, build sdist+wheel into wheelhouse. Returns dist name."""
    package_dir = package_dir.resolve()
    if not (package_dir / "pyproject.toml").is_file():
        raise FileNotFoundError(f"not a package dir: {package_dir}")
    dist_name = read_project_name(package_dir)
    extension_root = package_dir.parent
    src_blueprints = extension_root / "blueprints"
    has_blueprints = src_blueprints.is_dir() and any(src_blueprints.glob("*.json"))

    with tempfile.TemporaryDirectory(prefix="handlers-prepare-") as raw:
        work = Path(raw) / extension_root.name
        dest_pkg = work / "package"
        shutil.copytree(
            package_dir,
            dest_pkg,
            ignore=shutil.ignore_patterns(
                "*.egg-info", "build", "dist", "__pycache__", ".pytest_cache"
            ),
        )
        if has_blueprints:
            shutil.copytree(src_blueprints, work / "blueprints")
            staged = stage_extension_blueprints(extension_root=work)
            if staged:
                print(f"  staged blueprints -> {staged}")
        print(f"build {dist_name} from {package_dir}")
        subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(wheelhouse), str(dest_pkg)],
            check=True,
        )
    return dist_name


def _copy_artifacts_for_packages(
    artifacts_dir: Path, wheelhouse: Path, packages: list[str]
) -> None:
    for dist_name in packages:
        matches = _find_artifacts(artifacts_dir, dist_name)
        if not matches:
            raise RuntimeError(
                f"no artifact for {dist_name!r} under {artifacts_dir}"
            )
        for src in matches:
            dest = wheelhouse / src.name
            if dest.exists() and dest.stat().st_size == src.stat().st_size:
                print(f"  keep existing {dest.name}")
                continue
            print(f"  copy {src.name} -> wheelhouse/")
            shutil.copy2(src, dest)


def _preferred_sdist(wheelhouse: Path, dist_name: str) -> Path | None:
    sdists = [
        p
        for p in _find_artifacts(wheelhouse, dist_name)
        if p.name.endswith((".tar.gz", ".zip"))
    ]
    return sdists[0] if sdists else None


def extract_assets(wheelhouse: Path, assets_dir: Path, packages: list[str]) -> None:
    """Pull lambda_router.py / handlers_config.json from sdists into assets_dir."""
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    assets_dir.mkdir(parents=True)
    extras = assets_dir / "extras"
    primary_router_set = False
    primary_config_set = False

    for dist_name in packages:
        sdist = _preferred_sdist(wheelhouse, dist_name)
        if sdist is None:
            print(
                f"WARNING: no sdist for {dist_name}; skipping asset extract "
                f"(router/config may be missing)",
                file=sys.stderr,
            )
            continue
        with tempfile.TemporaryDirectory(prefix="handlers-assets-") as raw:
            root = _unpack_sdist_root(sdist, Path(raw))
            router = root / "lambda_router.py"
            config = root / "handlers_config.json"
            norm = normalize_dist_name(dist_name)
            if router.is_file() and not primary_router_set:
                shutil.copy2(router, assets_dir / "lambda_router.py")
                primary_router_set = True
                print(f"  primary lambda_router.py from {dist_name}")
            if config.is_file():
                if not primary_config_set:
                    shutil.copy2(config, assets_dir / "handlers_config.json")
                    primary_config_set = True
                    print(f"  primary handlers_config.json from {dist_name}")
                else:
                    dest = extras / norm
                    dest.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(config, dest / "handlers_config.json")
                    print(f"  extra handlers_config.json -> extras/{norm}/")

    if not (assets_dir / "lambda_router.py").is_file():
        raise RuntimeError(
            "no lambda_router.py found in any sdist; ensure MANIFEST.in includes it"
        )
    if not (assets_dir / "handlers_config.json").is_file():
        raise RuntimeError(
            "no handlers_config.json found in any sdist; ensure MANIFEST.in includes it"
        )


def download_deps(
    wheelhouse: Path,
    packages: list[str],
    *,
    platform: str = "manylinux2014_x86_64",
    python_version: str = "3.12",
) -> None:
    """Download transitive deps into wheelhouse so Docker can use --no-index.

    Defaults to Lambda's linux/amd64 tags so a Windows host does not poison the
    wheelhouse with win_amd64 wheels.
    """
    if not packages:
        return
    print(
        f"pip download deps for: {', '.join(packages)} "
        f"(platform={platform}, python={python_version})"
    )
    abi = f"cp{python_version.replace('.', '')}"
    base = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--dest",
        str(wheelhouse),
        "--find-links",
        str(wheelhouse),
        "--platform",
        platform,
        "--python-version",
        python_version,
        "--implementation",
        "cp",
        "--abi",
        abi,
        "--only-binary=:all:",
    ]
    try:
        subprocess.run([*base, *packages], check=True)
        return
    except subprocess.CalledProcessError:
        print(
            "WARNING: bulk pip download failed; trying per-package "
            "(private deps may be missing until CodeArtifact login)",
            file=sys.stderr,
        )
    for pkg in packages:
        try:
            subprocess.run([*base, pkg], check=True)
        except subprocess.CalledProcessError as exc:
            print(
                f"WARNING: pip download failed for {pkg!r} (exit {exc.returncode}); "
                f"ensure the dist and its deps are already in the wheelhouse",
                file=sys.stderr,
            )


def prepare(
    *,
    out_dir: Path,
    from_monorepo: list[Path],
    from_artifacts: Path | None,
    packages: list[str] | None,
    skip_deps: bool,
) -> list[str]:
    out_dir = out_dir.resolve()
    wheelhouse = out_dir / "wheelhouse"
    assets_dir = out_dir / "handlers-assets"
    wheelhouse.mkdir(parents=True, exist_ok=True)

    ordered: list[str] = []
    for pkg_dir in from_monorepo:
        name = _build_local_package(pkg_dir, wheelhouse)
        ordered.append(name)

    if packages:
        # Explicit order wins when provided; monorepo names must be a subset or match.
        for name in packages:
            if name not in ordered and normalize_dist_name(name) not in {
                normalize_dist_name(n) for n in ordered
            }:
                ordered.append(name)
        # Reorder: use --packages as install order when given
        by_norm = {normalize_dist_name(n): n for n in ordered}
        reordered: list[str] = []
        for name in packages:
            key = normalize_dist_name(name)
            reordered.append(by_norm.get(key, name))
        for name in ordered:
            if normalize_dist_name(name) not in {normalize_dist_name(n) for n in reordered}:
                reordered.append(name)
        ordered = reordered

    if from_artifacts is not None:
        if not ordered and not packages:
            raise ValueError("--from-artifacts requires --packages (install order)")
        target_names = packages or ordered
        _copy_artifacts_for_packages(from_artifacts, wheelhouse, target_names)
        if not ordered:
            ordered = list(target_names)

    if not ordered:
        raise ValueError("no packages to prepare; pass --from-monorepo and/or --packages")

    if not skip_deps:
        download_deps(wheelhouse, ordered)

    extract_assets(wheelhouse, assets_dir, ordered)

    meta = {
        "packages": ordered,
        "wheelhouse": str(wheelhouse),
        "assets": str(assets_dir),
    }
    (out_dir / "prepare_manifest.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return ordered


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare handlers wheelhouse/ + handlers-assets/ for Lambda builds"
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output directory (creates wheelhouse/ and handlers-assets/)",
    )
    parser.add_argument(
        "--from-monorepo",
        default="",
        help="Comma-separated package/ dirs to build (python -m build)",
    )
    parser.add_argument(
        "--from-artifacts",
        default="",
        help="Directory of already-downloaded sdists/wheels to copy into wheelhouse",
    )
    parser.add_argument(
        "--packages",
        default="",
        help="Ordered dist names (PyPI names). Required with --from-artifacts alone.",
    )
    parser.add_argument(
        "--skip-deps",
        action="store_true",
        help="Do not pip download transitive deps into the wheelhouse",
    )
    args = parser.parse_args()

    monorepo = [
        Path(p.strip())
        for p in args.from_monorepo.split(",")
        if p.strip()
    ]
    artifacts = Path(args.from_artifacts) if args.from_artifacts.strip() else None
    packages = [
        p.strip() for p in args.packages.split(",") if p.strip()
    ] or None

    if not monorepo and artifacts is None:
        print(
            "ERROR: pass --from-monorepo and/or --from-artifacts",
            file=sys.stderr,
        )
        return 1
    if artifacts is not None and not artifacts.is_dir():
        print(f"ERROR: artifacts directory not found: {artifacts}", file=sys.stderr)
        return 1
    for pkg in monorepo:
        if not pkg.is_dir():
            print(f"ERROR: package dir not found: {pkg}", file=sys.stderr)
            return 1

    try:
        ordered = prepare(
            out_dir=Path(args.out),
            from_monorepo=monorepo,
            from_artifacts=artifacts,
            packages=packages,
            skip_deps=args.skip_deps,
        )
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"prepared {len(ordered)} package(s): {', '.join(ordered)}")
    print(f"  wheelhouse: {Path(args.out).resolve() / 'wheelhouse'}")
    print(f"  assets:     {Path(args.out).resolve() / 'handlers-assets'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
