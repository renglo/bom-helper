from __future__ import annotations

import argparse
import sys
from pathlib import Path

from extensions_cli import commands
from extensions_cli.errors import ExtensionsError
from extensions_cli.help_text import format_help_text, help_payload
from extensions_cli.output import emit, fail
from extensions_cli.workspace import find_workspace


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    as_json = bool(getattr(args, "json", False))
    if args.cmd == "help":
        topic = getattr(args, "topic", "") or ""
        emit(help_payload(topic), as_json, format_help_text(topic))
        return 0
    try:
        workspace = find_workspace(Path(args.workspace) if getattr(args, "workspace", None) else None)
        payload, text = _dispatch(workspace, args)
    except ExtensionsError as exc:
        return fail(exc.message, as_json)
    emit(payload, as_json, text)
    if payload.get("ok") is False:
        return 1
    return 0


def _dispatch(workspace: Path, args: argparse.Namespace) -> tuple[dict, str]:
    cmd = args.cmd
    if cmd == "status":
        data = commands.status(workspace)
        return data, _status_text(data)
    if cmd == "show":
        data = commands.show_handle(workspace, args.handle)
        return data, _show_text(data)
    if cmd == "tree":
        data = commands.tree(workspace)
        return data, _tree_text(data)
    if cmd == "install":
        return _install(workspace, args)
    raise ExtensionsError(f"unknown command: {cmd}")


def _install(workspace: Path, args: argparse.Namespace) -> tuple[dict, str]:
    sub = args.install_cmd
    if sub == "help":
        return help_payload("install"), format_help_text("install")
    if sub == "place":
        data = commands.place(
            workspace,
            args.handle,
            hub=bool(args.hub),
            peer=args.peer or "",
            new_peer=args.new_peer or "",
            compute=args.compute or "fargate",
            task_size=args.task_size or "medium",
            python_version=args.python_version or "",
            npm=args.npm or "",
            aws_profile=args.profile or "",
            aws_region=args.region or "",
        )
        return data, (
            f"placed {data['sheet']['handle']} on {data['sheet']['path']} "
            f"{data['sheet'].get('peer_id') or ''} "
            f"(profile {data['sheet']['aws_profile']})\nnext: {data['next']}"
        )
    if sub == "plan":
        data = commands.plan(workspace)
        return data, _plan_text(data)
    if sub == "config":
        data = commands.config(workspace)
        return data, f"wrote {data['wrote']}\nnext: {data['next']}"
    if sub == "pin":
        data = commands.pin(workspace, args.python_version or "", args.npm_version or "")
        pin = data["pin"]
        return data, f"pin {pin['from']} → {pin['to']} ({pin['pin']})\nnext: {data['next']}"
    if sub == "publish":
        data = commands.publish(workspace, skip_upload=bool(args.skip_upload))
        extra = " (not uploaded)" if not data.get("uploaded") else ""
        return data, f"wheel {data['wheel']}{extra}\nnext: {data['next']}"
    if sub == "deploy":
        data = commands.deploy(workspace, dry_run=bool(args.dry_run))
        cmds = "\n".join(f"  {c}" for c in data.get("commands") or [])
        prefix = "dry-run:\n" if data.get("dry_run") else "deployed:\n"
        return data, f"{prefix}{cmds}\nnext: {data['next']}"
    if sub == "test":
        data = commands.test(workspace, skip_synth=bool(args.skip_synth))
        return data, f"test ok ({data['checks']['unique_owner']})\nnext: {data['next']}"
    if sub == "push":
        data = commands.push(workspace, yes=bool(args.yes), no_push=bool(args.no_push))
        return data, f"BOM {data['git']['commit']} pushed={data['git']['pushed']}\nnext: {data['next']}"
    if sub == "finish":
        data = commands.finish(workspace)
        return data, (
            f"{data['handle']} role=product. {data['convoy']}\n"
            f"sheet {data['sheet']}. {data['next']}"
        )
    raise ExtensionsError(f"unknown install command: {sub}")


def _status_text(data: dict) -> str:
    if not data.get("incubating"):
        return f"{data['hint']}\nnext: {data['next']}"
    sheet = data["sheet"]
    return (
        f"handle:   {sheet.get('handle')}\n"
        f"path:     {sheet.get('path')} {sheet.get('peer_id') or ''}\n"
        f"profile:  {sheet.get('aws_profile') or '(missing)'}\n"
        f"region:   {sheet.get('aws_region') or '(from config)'}\n"
        f"phase:    {sheet.get('phase')}\n"
        f"test:     {sheet.get('test') or 'not run'}\n"
        f"next:     {data['next']}"
    )


def _show_text(data: dict) -> str:
    owners = ", ".join(data.get("owners") or []) or "(not in catalog)"
    return (
        f"handle:    {data['handle']}\n"
        f"python:    {data['python']}\n"
        f"owners:    {owners}\n"
        f"role:      {data['role']}\n"
        f"installer: {data['installer']}\n"
        f"env:       {data['env']}"
    )


def _tree_text(data: dict) -> str:
    rows = data.get("extensions") or []
    if not rows:
        return f"{data['env']}: no catalog extensions"
    lines = [f"{data['env']}"]
    for row in rows:
        lines.append(f"  {row['handle']:20} {row['owner']:16} {row['python']}")
    return "\n".join(lines)


def _plan_text(data: dict) -> str:
    cfg = data["config"]
    lines = [
        f"handle:  {data['sheet']['handle']}",
        f"config:  {cfg['file']}  packages.{cfg['packages']}  {cfg['placement']}",
        f"pin:     {data['pin']}",
        f"publish: {data['publish']}",
        "deploy:",
    ]
    for cmd in data.get("deploy_commands") or []:
        lines.append(f"  {cmd}")
    lines.append(f"push:    {data['push']}")
    lines.append("skip:    " + ", ".join(data["skip"]))
    lines.append(f"next:    {data['next']}")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extensions",
        description="Install an incubating extension and inspect catalog placement.",
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--workspace", default=None, help="Monorepo root (extensions/ + ops/)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_help = sub.add_parser("help", help="List commands")
    p_help.add_argument("topic", nargs="?", default="")

    sub.add_parser("status", help="Incubation sheet and next step")

    p_show = sub.add_parser("show", help="One handle in the catalog")
    p_show.add_argument("handle")

    sub.add_parser("tree", help="Catalog map of all handles")

    inst = sub.add_parser("install", help="One-time incubation")
    isub = inst.add_subparsers(dest="install_cmd", required=True)
    isub.add_parser("help", help="Install verbs")

    p_place = isub.add_parser("place", help="Start a sheet")
    p_place.add_argument("handle")
    p_place.add_argument("--hub", action="store_true")
    p_place.add_argument("--peer", default="")
    p_place.add_argument("--new-peer", default="")
    p_place.add_argument("--compute", default="fargate")
    p_place.add_argument("--task-size", default="medium")
    p_place.add_argument("--python-version", default="")
    p_place.add_argument("--npm", default="")
    p_place.add_argument(
        "--profile",
        required=True,
        help="AWS CLI profile for deploy/publish (stored on the incubation sheet)",
    )
    p_place.add_argument(
        "--region",
        default="",
        help="AWS region (default: aws_region from customer-config.json)",
    )

    isub.add_parser("plan", help="Print the plan")
    isub.add_parser("config", help="Edit deploy_targets.yml")

    p_pin = isub.add_parser("pin", help="Bump BOM pin file")
    p_pin.add_argument("--python-version", default="")
    p_pin.add_argument("--npm-version", default="")

    p_pub = isub.add_parser("publish", help="Build / upload first wheel")
    p_pub.add_argument("--skip-upload", action="store_true")

    p_dep = isub.add_parser("deploy", help="Owning stack + write-state")
    p_dep.add_argument("--dry-run", action="store_true")

    p_test = isub.add_parser("test", help="Installer and unique owner")
    p_test.add_argument("--skip-synth", action="store_true")

    p_push = isub.add_parser("push", help="Commit/push *-bom main")
    p_push.add_argument("--yes", action="store_true")
    p_push.add_argument("--no-push", action="store_true", help="Commit only")

    isub.add_parser("finish", help="role=product and clear the sheet")
    return parser


if __name__ == "__main__":
    sys.exit(main())
