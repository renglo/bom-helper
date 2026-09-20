from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from extensions_cli.aws_session import apply_to_env, resolve_aws
from extensions_cli.errors import ExtensionsError
from extensions_cli.workspace import find_bom_root, helper_venv_python


def package_dir(folder: Path) -> Path:
    if (folder / "package" / "pyproject.toml").is_file():
        return folder / "package"
    if (folder / "pyproject.toml").is_file():
        return folder
    raise ExtensionsError(f"no pyproject.toml under {folder}")


def build_wheel(folder: Path) -> Path:
    root = package_dir(folder)
    dist = root / "dist"
    if dist.is_dir():
        shutil.rmtree(dist)
    python = helper_venv_python()
    exe = str(python) if python.is_file() else "python3"
    result = subprocess.run(
        [exe, "-m", "build", str(root)],
        cwd=str(root.parent if root.name == "package" else root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # `python -m build package` from extension root (publisher style)
        result = subprocess.run(
            [exe, "-m", "build", "package"],
            cwd=str(folder),
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        raise ExtensionsError(
            "wheel build failed (pip install build). "
            f"{(result.stderr or result.stdout or '').strip()[-400:]}"
        )
    wheels = sorted((root / "dist").glob("*.whl")) if (root / "dist").is_dir() else []
    if not wheels:
        wheels = sorted((folder / "package" / "dist").glob("*.whl"))
    if not wheels:
        raise ExtensionsError("build succeeded but no .whl found under package/dist")
    return wheels[-1]


def upload_wheel(
    workspace: Path,
    wheel: Path,
    *,
    sheet: dict | None = None,
) -> dict[str, Any]:
    profile, region = resolve_aws(sheet, workspace, require_sheet=bool(sheet))
    apply_to_env(profile, region)
    bom = find_bom_root(workspace)
    try:
        import yaml
    except ImportError as exc:
        raise ExtensionsError("PyYAML required") from exc
    data = yaml.safe_load((bom / "deploy_targets.yml").read_text(encoding="utf-8")) or {}
    registries = data.get("registries") or []
    domain = "arbitium"
    owner = ""
    repo = "python-store"
    if registries and isinstance(registries[0], dict):
        domain = str(registries[0].get("domain") or domain)
        owner = str(registries[0].get("domain_owner") or "")
        repo = str(registries[0].get("python_repository") or repo)
    login = [
        "aws",
        "codeartifact",
        "login",
        "--tool",
        "twine",
        "--domain",
        domain,
        "--repository",
        repo,
    ]
    if owner:
        login.extend(["--domain-owner", owner])
    logged = subprocess.run(login, capture_output=True, text=True)
    if logged.returncode != 0:
        raise ExtensionsError(
            "aws codeartifact login failed. "
            f"{(logged.stderr or logged.stdout or '').strip()[-300:]}"
        )
    twine = shutil.which("twine")
    python = helper_venv_python()
    cmd = [str(python), "-m", "twine", "upload", "--repository", "codeartifact", str(wheel)]
    if not python.is_file():
        cmd = [twine or "twine", "upload", "--repository", "codeartifact", str(wheel)]
    uploaded = subprocess.run(cmd, capture_output=True, text=True)
    if uploaded.returncode != 0:
        raise ExtensionsError(
            "twine upload failed. "
            f"{(uploaded.stderr or uploaded.stdout or '').strip()[-400:]}"
        )
    return {"wheel": str(wheel), "domain": domain, "repository": repo}
