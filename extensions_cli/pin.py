from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from extensions_cli.catalog import current_bom_version, pin_file, python_dist, read_pin, slots
from extensions_cli.catalog_edit import set_version_pointer
from extensions_cli.errors import ExtensionsError
from extensions_cli.workspace import find_bom_root


def bump_patch(version: str) -> str:
    raw = (version or "").strip().lstrip("v")
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", raw)
    if not match:
        raise ExtensionsError(f"cannot bump BOM version {version!r}")
    major, minor, patch = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return f"{major}.{minor}.{patch + 1}"


def read_python_version(folder: Path) -> str:
    for candidate in (folder / "package" / "pyproject.toml", folder / "pyproject.toml"):
        if not candidate.is_file():
            continue
        match = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)["\']', candidate.read_text())
        if match:
            return match.group(1).strip()
    raise ExtensionsError(
        f"no version in {folder}/package/pyproject.toml; pass --python-version"
    )


def source_pin_path(bom_root: Path, *, path: str, peer_id: str, current: str) -> Path:
    current = current.lstrip("v")
    if path == "hub":
        hub = bom_root / "bom" / f"v{current}.json"
        if hub.is_file():
            return hub
        raise ExtensionsError(f"hub pin not found: {hub}")
    peer = bom_root / "peers_bom" / peer_id / f"v{current}.json"
    if peer.is_file():
        return peer
    peers_root = bom_root / "peers_bom"
    if peers_root.is_dir():
        for other in sorted(peers_root.iterdir()):
            candidate = other / f"v{current}.json"
            if candidate.is_file():
                return candidate
            versions = sorted(other.glob("v*.json"))
            if versions:
                return versions[-1]
    hub = bom_root / "bom" / f"v{current}.json"
    if hub.is_file():
        return hub
    raise ExtensionsError(f"no pin file to copy for peers_bom/{peer_id}/v{current}.json")


def write_bumped_pin(
    workspace: Path,
    *,
    path: str,
    peer_id: str,
    handle: str,
    python_version: str,
    npm: str = "",
    npm_version: str = "",
) -> dict[str, str]:
    bom_root = find_bom_root(workspace)
    targets = bom_root / "deploy_targets.yml"
    text = targets.read_text(encoding="utf-8")
    import yaml

    data = yaml.safe_load(text) or {}
    current = current_bom_version(data, path=path, peer_id=peer_id)
    if not current:
        current = str(data.get("bom") or "0.0.0").lstrip("v")
    new_ver = bump_patch(current)
    dist = python_dist(bom_root, handle)
    src = source_pin_path(bom_root, path=path, peer_id=peer_id, current=current)
    dest = pin_file(bom_root, path=path, peer_id=peer_id, version=new_ver)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = read_pin(src)
    python = dict(payload.get("python") or {})
    python[dist] = python_version
    catalog = slots(bom_root)
    wl = next((s.python for s in catalog if s.python.endswith("-wl")), "")
    if path != "hub" and wl and wl not in python:
        hub_src = bom_root / "bom" / f"v{current}.json"
        if hub_src.is_file():
            hub_py = (read_pin(hub_src).get("python") or {})
            if wl in hub_py:
                python[wl] = hub_py[wl]
        if "renglo-lib" not in python and hub_src.is_file():
            lib = (read_pin(hub_src).get("python") or {}).get("renglo-lib")
            if lib:
                python["renglo-lib"] = lib
    payload["python"] = python
    payload["version"] = f"v{new_ver}"
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if path == "hub":
        text = set_version_pointer(text, "bom", new_ver)
        if npm:
            console_src = bom_root / "console_bom" / f"v{current}.json"
            console_dest = bom_root / "console_bom" / f"v{new_ver}.json"
            if console_src.is_file():
                shutil.copy2(console_src, console_dest)
                cons = json.loads(console_dest.read_text(encoding="utf-8"))
                npm_map = dict(cons.get("npm") or {})
                if npm_version:
                    npm_map[npm] = npm_version
                cons["npm"] = npm_map
                cons["version"] = f"v{new_ver}"
                console_dest.write_text(json.dumps(cons, indent=2) + "\n", encoding="utf-8")
            text = set_version_pointer(text, "console_bom", new_ver)
    else:
        text = set_version_pointer(text, "peers_bom", new_ver, peer_id=peer_id)
    targets.write_text(text, encoding="utf-8")
    return {
        "from": current,
        "to": new_ver,
        "pin": str(dest.relative_to(bom_root)),
        "dist": dist,
        "python_version": python_version,
    }
