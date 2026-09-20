from __future__ import annotations

import json
from typing import Any

from extensions_cli.catalog import (
    catalog_peers,
    load_targets,
    owners_for_handle,
    python_dist,
    require_unique_place,
    slot_for_handle,
    tree_rows,
    validate_compute,
    slots,
)
from extensions_cli.catalog_edit import (
    add_hub_python,
    add_new_peer,
    add_peer_extension,
    add_peer_python,
    ensure_package_slot,
)
from extensions_cli.deploy import plan_commands, run_deploy
from extensions_cli.errors import ExtensionsError
from extensions_cli.pin import read_python_version, write_bumped_pin
from extensions_cli.publish import build_wheel, upload_wheel
from extensions_cli.gitops import commit_and_push_bom, convoy_init
from extensions_cli.state import (
    NEXT_COMMAND,
    clear,
    load,
    next_hint,
    require,
    save,
    set_phase,
)
from extensions_cli.workspace import (
    deploy_targets_path,
    env_name,
    extension_folder,
    find_bom_root,
    gitconvoy_toml,
    load_customer_config,
    read_repo_role,
    require_installer,
    write_repo_role,
)


def status(workspace) -> dict[str, Any]:
    sheet = load(workspace)
    if sheet is None:
        return {
            "ok": True,
            "incubating": False,
            "next": next_hint(None),
            "hint": "Nothing incubating. Place a handle or run extensions tree.",
        }
    return {
        "ok": True,
        "incubating": True,
        "sheet": sheet,
        "next": next_hint(sheet),
        "hint": f"Next: {next_hint(sheet)}",
    }


def show_handle(workspace, handle: str) -> dict[str, Any]:
    handle = handle.strip()
    bom = find_bom_root(workspace)
    data = load_targets(bom / "deploy_targets.yml")
    dist = python_dist(bom, handle)
    owners = owners_for_handle(data, handle, dist)
    folder = workspace / "extensions" / handle
    role = read_repo_role(folder) if folder.is_dir() else ""
    installer = (folder / "installer" / "infra" / "cdk_extension.json").is_file()
    return {
        "ok": True,
        "handle": handle,
        "python": dist,
        "owners": owners,
        "role": role or "(missing folder)",
        "installer": installer,
        "env": env_name(workspace),
    }


def tree(workspace) -> dict[str, Any]:
    bom = find_bom_root(workspace)
    data = load_targets(bom / "deploy_targets.yml")
    rows = tree_rows(data, slots(bom))
    return {"ok": True, "env": env_name(workspace), "extensions": rows}


def place(
    workspace,
    handle: str,
    *,
    hub: bool,
    peer: str,
    new_peer: str,
    compute: str,
    task_size: str,
    python_version: str,
    npm: str,
    aws_profile: str,
    aws_region: str = "",
) -> dict[str, Any]:
    handle = handle.strip()
    profile = (aws_profile or "").strip()
    if not profile:
        raise ExtensionsError("install place requires --profile <aws-profile>")
    cfg = load_customer_config(workspace)
    region = (aws_region or str(cfg.get("aws_region") or "us-east-1")).strip() or "us-east-1"
    flags = [hub, bool(peer.strip()), bool(new_peer.strip())]
    if sum(1 for f in flags if f) != 1:
        raise ExtensionsError("choose exactly one of --hub, --peer PEER, --new-peer PEER")
    folder = require_installer(workspace, handle)
    bom = find_bom_root(workspace)
    data = load_targets(bom / "deploy_targets.yml")
    dist = python_dist(bom, handle)
    existing = owners_for_handle(data, handle, dist)
    toml = gitconvoy_toml(folder)
    role = read_repo_role(folder)
    if toml.is_file() and role == "product":
        raise ExtensionsError(
            f"{handle} is already role=product. Use git convoy for releases; "
            "extensions install is incubating only."
        )
    if existing:
        raise ExtensionsError(
            f"{handle} is already in the catalog ({', '.join(existing)}). "
            "install is for new handles only."
        )
    write_repo_role(folder, "incubating")
    role = "incubating"
    if hub:
        path, peer_id = "hub", ""
        require_unique_place(data, handle=handle, dist=dist, path="hub", peer_id="")
    elif peer.strip():
        path, peer_id = "peer", peer.strip()
        require_unique_place(data, handle=handle, dist=dist, path="peer", peer_id=peer_id)
    else:
        path, peer_id = "new-peer", new_peer.strip()
        require_unique_place(data, handle=handle, dist=dist, path="new-peer", peer_id=peer_id)
        compute = validate_compute(compute)

    sheet = {
        "handle": handle,
        "path": path,
        "peer_id": peer_id,
        "compute": compute if path == "new-peer" else "",
        "task_size": task_size if path == "new-peer" else "",
        "python_dist": dist,
        "npm": npm.strip(),
        "python_version": python_version.strip(),
        "phase": "placed",
        "test": None,
        "files": [],
        "role": role,
        "env": env_name(workspace),
        "aws_profile": profile,
        "aws_region": region,
    }
    save(workspace, sheet)
    return {"ok": True, "sheet": sheet, "next": NEXT_COMMAND["placed"]}


def plan(workspace) -> dict[str, Any]:
    sheet = require(workspace)
    handle = str(sheet["handle"])
    path = str(sheet["path"])
    peer_id = str(sheet.get("peer_id") or "")
    dist = str(sheet.get("python_dist") or handle)
    files = ["ops/<bom>/deploy_targets.yml  (packages + placement)"]
    if path == "hub":
        files.append("ops/<bom>/bom/vNEXT.json  (after pin)")
        stacks = ["Deploy Stack B", "write-state"]
    else:
        files.append(f"ops/<bom>/peers_bom/{peer_id or 'PEER'}/vNEXT.json  (after pin)")
        stacks = [f"Deploy {{env}}-peer-{peer_id or 'PEER'}", "write-state"]
    return {
        "ok": True,
        "sheet": sheet,
        "config": {
            "file": "deploy_targets.yml",
            "packages": handle,
            "placement": "hub.python" if path == "hub" else f"peers.{peer_id}.extensions + python",
            "python": dist,
        },
        "pin": "new BOM version + pointer (not an in-place edit of the current file)",
        "publish": "first CodeArtifact wheel (not a train tag)",
        "deploy": stacks,
        "deploy_commands": plan_commands(workspace, sheet),
        "push": "*-bom main after pin (this tool, once)",
        "skip": ["Stack A", "customer-config.json", "git convoy adopt"],
        "files": files,
        "next": next_hint(sheet),
    }


def config(workspace) -> dict[str, Any]:
    sheet = require(workspace)
    _refuse_product(workspace, sheet)
    handle = str(sheet["handle"])
    dist = str(sheet.get("python_dist") or handle)
    npm = str(sheet.get("npm") or "")
    path = str(sheet["path"])
    peer_id = str(sheet.get("peer_id") or "")
    bom = find_bom_root(workspace)
    targets = bom / "deploy_targets.yml"
    text = targets.read_text(encoding="utf-8")
    text = ensure_package_slot(text, handle, dist, npm)
    if path == "hub":
        text = add_hub_python(text, dist)
    elif path == "peer":
        text = add_peer_extension(text, peer_id, handle)
        text = add_peer_python(text, peer_id, dist)
    else:
        data = load_targets(targets)
        current = str(data.get("bom") or "0.0.1").lstrip("v")
        for peer in catalog_peers(data):
            if peer.get("peers_bom"):
                current = str(peer["peers_bom"]).lstrip("v")
                break
        text = add_new_peer(
            text,
            peer_id=peer_id,
            handle=handle,
            dist=dist,
            compute=str(sheet.get("compute") or "fargate"),
            task_size=str(sheet.get("task_size") or "medium"),
            peers_bom=current,
        )
    targets.write_text(text, encoding="utf-8")
    rel = str(targets.relative_to(find_bom_root(workspace)))
    sheet.setdefault("files", [])
    if rel not in sheet["files"]:
        sheet["files"].append(rel)
    set_phase(sheet, "configured")
    save(workspace, sheet)
    return {"ok": True, "wrote": rel, "sheet": sheet, "next": NEXT_COMMAND["configured"]}


def pin(workspace, python_version: str, npm_version: str) -> dict[str, Any]:
    sheet = require(workspace)
    _refuse_product(workspace, sheet)
    handle = str(sheet["handle"])
    folder = extension_folder(workspace, handle)
    version = (python_version or str(sheet.get("python_version") or "")).strip()
    if not version:
        version = read_python_version(folder)
    path = str(sheet["path"])
    pin_path = "hub" if path == "hub" else "peer"
    result = write_bumped_pin(
        workspace,
        path=pin_path,
        peer_id=str(sheet.get("peer_id") or ""),
        handle=handle,
        python_version=version,
        npm=str(sheet.get("npm") or ""),
        npm_version=npm_version,
    )
    sheet["python_version"] = version
    sheet["bom_version"] = result["to"]
    sheet.setdefault("files", [])
    if result["pin"] not in sheet["files"]:
        sheet["files"].append(result["pin"])
    set_phase(sheet, "pinned")
    save(workspace, sheet)
    return {"ok": True, "pin": result, "next": NEXT_COMMAND["pinned"]}


def publish(workspace, *, skip_upload: bool) -> dict[str, Any]:
    sheet = require(workspace)
    _refuse_product(workspace, sheet)
    folder = extension_folder(workspace, str(sheet["handle"]))
    wheel = build_wheel(folder)
    payload: dict[str, Any] = {"ok": True, "wheel": str(wheel), "uploaded": False}
    if not skip_upload:
        payload.update(upload_wheel(workspace, wheel, sheet=sheet))
        payload["uploaded"] = True
    set_phase(sheet, "published")
    save(workspace, sheet)
    payload["next"] = NEXT_COMMAND["published"]
    return payload


def deploy(workspace, *, dry_run: bool) -> dict[str, Any]:
    sheet = require(workspace)
    _refuse_product(workspace, sheet)
    result = run_deploy(workspace, sheet, dry_run=dry_run)
    if not dry_run:
        set_phase(sheet, "deployed")
        save(workspace, sheet)
    result["next"] = NEXT_COMMAND["deployed"] if not dry_run else next_hint(sheet)
    return result


def test(workspace, *, skip_synth: bool) -> dict[str, Any]:
    sheet = require(workspace)
    handle = str(sheet["handle"])
    require_installer(workspace, handle)
    bom = find_bom_root(workspace)
    data = load_targets(bom / "deploy_targets.yml")
    dist = str(sheet.get("python_dist") or handle)
    owners = owners_for_handle(data, handle, dist)
    if len(owners) != 1:
        raise ExtensionsError(f"{handle} owners={owners or 'none'}; expected exactly one")
    checks = {
        "installer": True,
        "unique_owner": owners[0],
        "role": read_repo_role(extension_folder(workspace, handle)),
        "synth": "skipped",
    }
    if not skip_synth:
        from extensions_cli.deploy import plan_commands

        checks["synth"] = "not-run (use deploy --dry-run to print cdk synth)"
        _ = plan_commands
    sheet["test"] = {"ok": True, "checks": checks}
    set_phase(sheet, "tested")
    save(workspace, sheet)
    return {"ok": True, "checks": checks, "next": NEXT_COMMAND["tested"]}


def push(workspace, *, yes: bool, no_push: bool) -> dict[str, Any]:
    sheet = require(workspace)
    _refuse_product(workspace, sheet)
    if str(sheet.get("phase")) not in ("tested", "pushed", "published", "pinned", "deployed"):
        raise ExtensionsError("run pin (and usually test) before push")
    bom = find_bom_root(workspace)
    handle = str(sheet["handle"])
    paths = ["deploy_targets.yml", "bom", "console_bom", "peers_bom"]
    result = commit_and_push_bom(
        bom,
        message=f"Install extension {handle} on {sheet.get('path')} {sheet.get('peer_id') or 'hub'}.".strip(),
        paths=paths,
        yes=yes,
        push=not no_push,
    )
    set_phase(sheet, "pushed")
    save(workspace, sheet)
    return {"ok": True, "git": result, "next": NEXT_COMMAND["pushed"]}


def finish(workspace) -> dict[str, Any]:
    sheet = require(workspace)
    handle = str(sheet["handle"])
    if str(sheet.get("phase")) != "pushed":
        raise ExtensionsError(
            f"finish requires phase=pushed (now {sheet.get('phase')}). {next_hint(sheet)}"
        )
    if not (sheet.get("test") or {}).get("ok"):
        raise ExtensionsError("finish requires a passing extensions install test")
    folder = extension_folder(workspace, handle)
    toml = write_repo_role(folder, "product")
    init_msg = convoy_init(workspace)
    clear(workspace)
    return {
        "ok": True,
        "handle": handle,
        "role": "product",
        "gitconvoy_toml": str(toml),
        "convoy": init_msg,
        "sheet": "cleared",
        "next": "git convoy feature / train — this handle is product now",
    }


def _refuse_product(workspace, sheet: dict[str, Any]) -> None:
    folder = extension_folder(workspace, str(sheet["handle"]))
    if read_repo_role(folder) == "product":
        raise ExtensionsError(
            f"{sheet['handle']} is role=product. pins/publish/push are git convoy adopt."
        )
