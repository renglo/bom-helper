from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from extensions_cli.aws_session import apply_to_env, resolve_aws
from extensions_cli.errors import ExtensionsError
from extensions_cli.workspace import (
    bootstrap_install,
    env_name,
    helper_root,
    ops_dir,
)


def plan_commands(workspace: Path, sheet: dict[str, Any]) -> list[str]:
    env = env_name(workspace)
    try:
        profile, region = resolve_aws(sheet, workspace, require_sheet=True)
    except ExtensionsError:
        profile, region = "<aws-profile>", "us-east-1"
    ops = ops_dir(workspace)
    path = str(sheet.get("path") or "")
    peer_id = str(sheet.get("peer_id") or "")
    cmds: list[str] = []
    if path == "hub":
        cmds.extend(
            [
                f"cd {ops} && python3.12 bootstrap/install.py synth",
                (
                    f"cd {ops}/bootstrap/output/{env}/cdk && "
                    f'cdk deploy "{env}-stack-b" --app "../../../venv/bin/python app.py" '
                    f"--output . --exclusively --require-approval never --profile {profile}"
                ),
            ]
        )
    else:
        cmds.extend(
            [
                f"cd {helper_root()} && bash scripts/deploy_peer_cdk.sh synth --peer-id {peer_id}",
                f"cd {helper_root()} && bash scripts/deploy_peer_cdk.sh deploy --peer-id {peer_id}",
            ]
        )
    cmds.append(
        f"cd {ops} && python3.12 bootstrap/install.py write-state "
        f"--env-name {env} --aws-profile {profile} --aws-region {region}"
    )
    return cmds


def run_deploy(workspace: Path, sheet: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    commands = plan_commands(workspace, sheet)
    if dry_run:
        return {"ok": True, "dry_run": True, "commands": commands}
    env = env_name(workspace)
    profile, region = resolve_aws(sheet, workspace, require_sheet=True)
    apply_to_env(profile, region)
    os.environ["ENV"] = env
    path = str(sheet.get("path") or "")
    if path == "hub":
        _run_hub(workspace, env, profile)
    else:
        _run_peer(workspace, str(sheet.get("peer_id") or ""), profile)
    _run_write_state(workspace, env, profile, region)
    return {"ok": True, "dry_run": False, "commands": commands, "stack": _stack_name(env, sheet)}


def _stack_name(env: str, sheet: dict[str, Any]) -> str:
    if str(sheet.get("path") or "") == "hub":
        return f"{env}-stack-b"
    return f"{env}-peer-{sheet.get('peer_id')}"


def _run_hub(workspace: Path, env: str, profile: str) -> None:
    install = bootstrap_install(workspace)
    if not install.is_file():
        raise ExtensionsError(f"bootstrap install.py not found: {install}")
    _check(subprocess.run(["python3.12", str(install), "synth"], cwd=str(ops_dir(workspace))))
    cdk_dir = ops_dir(workspace) / "bootstrap" / "output" / env / "cdk"
    app = ops_dir(workspace) / "bootstrap" / "venv" / "bin" / "python"
    _check(
        subprocess.run(
            [
                "cdk",
                "deploy",
                f"{env}-stack-b",
                "--app",
                f"{app} app.py" if app.is_file() else "python app.py",
                "--output",
                ".",
                "--exclusively",
                "--require-approval",
                "never",
                "--profile",
                profile,
            ],
            cwd=str(cdk_dir),
        )
    )


def _run_peer(workspace: Path, peer_id: str, profile: str) -> None:
    if not peer_id:
        raise ExtensionsError("sheet missing peer_id")
    script = helper_root() / "scripts" / "deploy_peer_cdk.sh"
    env = {**os.environ, "ENV": env_name(workspace), "AWS_PROFILE": profile, "PEER_ID": peer_id}
    for action in ("synth", "deploy"):
        _check(
            subprocess.run(
                ["bash", str(script), action, "--peer-id", peer_id, "--profile", profile],
                cwd=str(helper_root()),
                env=env,
            )
        )


def _run_write_state(workspace: Path, env: str, profile: str, region: str) -> None:
    install = bootstrap_install(workspace)
    _check(
        subprocess.run(
            [
                "python3.12",
                str(install),
                "write-state",
                "--env-name",
                env,
                "--aws-profile",
                profile,
                "--aws-region",
                region,
            ],
            cwd=str(ops_dir(workspace)),
        )
    )


def _check(result: subprocess.CompletedProcess[Any]) -> None:
    if result.returncode != 0:
        raise ExtensionsError(f"command failed with exit {result.returncode}")
