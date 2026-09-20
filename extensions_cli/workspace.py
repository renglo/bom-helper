from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from extensions_cli.errors import ExtensionsError
from extensions_cli.state import state_path

_HELPER = Path(__file__).resolve().parents[1]

_MISSING_CWD = (
    "current directory no longer exists; cd to the workspace root or pass --workspace"
)


def _cwd() -> Path:
    try:
        return Path.cwd().resolve()
    except FileNotFoundError:
        pwd = os.environ.get("PWD", "").strip()
        if pwd and Path(pwd).exists():
            return Path(pwd).resolve()
        raise ExtensionsError(_MISSING_CWD) from None


def find_workspace(explicit: Path | None = None) -> Path:
    """Monorepo root (extensions/ + ops/). Walks up from cwd; finds an active sheet first."""
    override = os.environ.get("EXTENSIONS_WORKSPACE", "").strip()
    if explicit is not None:
        return explicit.expanduser().resolve()
    if override:
        return Path(override).expanduser().resolve()
    here = _cwd()
    for candidate in [here, *here.parents]:
        if state_path(candidate).is_file():
            return candidate
        if (candidate / "extensions").is_dir() and (candidate / "ops").is_dir():
            return candidate
    if (_HELPER.parent / "launcher").is_dir() and (_HELPER.parent.parent / "extensions").is_dir():
        return _HELPER.parent.parent
    raise ExtensionsError(
        "workspace root not found (need extensions/ and ops/). "
        "Run from the monorepo or pass --workspace."
    )


def ops_dir(workspace: Path) -> Path:
    return workspace / "ops"


def launcher_config(workspace: Path) -> Path:
    return ops_dir(workspace) / "launcher" / "cdk" / "customer-config.json"


def load_customer_config(workspace: Path) -> dict[str, Any]:
    path = launcher_config(workspace)
    if not path.is_file():
        raise ExtensionsError(f"customer-config.json not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ExtensionsError(f"{path}: expected a JSON object")
    return data


def env_name(workspace: Path) -> str:
    cfg = load_customer_config(workspace)
    name = str(cfg.get("env_name", "")).strip()
    if not name:
        raise ExtensionsError("customer-config.json: env_name is empty")
    return name


def find_bom_root(workspace: Path) -> Path:
    cfg = load_customer_config(workspace)
    github_repo = str(cfg.get("github_repo", "")).strip()
    checkout = github_repo.rstrip("/").split("/")[-1] if github_repo else ""
    ops = ops_dir(workspace)
    if checkout:
        candidate = ops / checkout
        if (candidate / "deploy_targets.yml").is_file():
            return candidate
    matches = sorted(p.parent for p in ops.glob("*-bom/deploy_targets.yml") if p.is_file())
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ExtensionsError(f"no *-bom/deploy_targets.yml under {ops}")
    raise ExtensionsError(
        "multiple BOM repos: " + ", ".join(p.name for p in matches) + "; set github_repo in customer-config.json"
    )


def deploy_targets_path(workspace: Path) -> Path:
    return find_bom_root(workspace) / "deploy_targets.yml"


def extension_folder(workspace: Path, handle: str) -> Path:
    handle = (handle or "").strip()
    folder = workspace / "extensions" / handle
    if not folder.is_dir():
        raise ExtensionsError(f"extension folder not found: {folder}")
    return folder


def installer_manifest(folder: Path) -> Path:
    return folder / "installer" / "infra" / "cdk_extension.json"


def require_installer(workspace: Path, handle: str) -> Path:
    folder = extension_folder(workspace, handle)
    manifest = installer_manifest(folder)
    if not manifest.is_file():
        raise ExtensionsError(
            f"{handle} is missing {manifest.relative_to(workspace)} "
            "(cdk_extension.json + policy JSON are required)"
        )
    policy_rel = ""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        policy_rel = str((data or {}).get("policy_file") or "").strip()
    except json.JSONDecodeError as exc:
        raise ExtensionsError(f"{manifest}: invalid JSON ({exc})") from exc
    if policy_rel:
        policy = folder / "installer" / "infra" / policy_rel
        if not policy.is_file():
            raise ExtensionsError(f"{handle} policy_file not found: {policy}")
    return folder


def gitconvoy_toml(folder: Path) -> Path:
    return folder / "gitconvoy.toml"


def read_repo_role(folder: Path) -> str:
    path = gitconvoy_toml(folder)
    if not path.is_file():
        return "product"
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("role"):
            _, _, value = line.partition("=")
            role = value.strip().strip("'\"")
            return role or "product"
    return "product"


def write_repo_role(folder: Path, role: str) -> Path:
    path = gitconvoy_toml(folder)
    text = (
        "# git-convoy membership marker (repo root).\n"
        "# role: product | aux | bom | incubating\n"
        f'role = "{role}"\n'
    )
    path.write_text(text, encoding="utf-8")
    return path


def helper_root() -> Path:
    return _HELPER


def helper_venv_python() -> Path:
    """bom-helper venv interpreter. bom-venv is current; venv is the legacy name."""
    names = [n for n in (os.environ.get("BOM_VENV_NAME"), "bom-venv", "venv") if n]
    for name in names:
        candidate = _HELPER / name / "bin" / "python"
        if candidate.is_file():
            return candidate
    return _HELPER / names[0] / "bin" / "python"


def bootstrap_install(workspace: Path) -> Path:
    return ops_dir(workspace) / "bootstrap" / "install.py"
