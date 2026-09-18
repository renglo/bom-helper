#!/usr/bin/env python3
"""Merge peer-stack CloudFormation outputs into SSM handle → peer map.

Does not remove overflow singleton ARNs (dual-run). Run after
``cdk deploy`` of ``{env}-peer-{peerId}``.

    python scripts/write_peer_routes.py deploy_targets.yml \\
        --env-name acme0813 --region us-east-1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from peers import load_peers, peer_stack_name  # noqa: E402


def _output(outputs: dict[str, str], logical: str) -> str:
    """Read a CDK output by logical id (exact or nested ``Compute…<id><hash>``)."""
    direct = (outputs.get(logical) or "").strip()
    if direct:
        return direct
    matches = [
        str(val).strip()
        for key, val in outputs.items()
        if logical in key and str(val).strip()
    ]
    return matches[0] if matches else ""


def _cfn_outputs(stack_name: str, region: str) -> dict[str, str]:
    import boto3
    from botocore.exceptions import ClientError

    cfn = boto3.client("cloudformation", region_name=region)
    try:
        stacks = cfn.describe_stacks(StackName=stack_name).get("Stacks") or []
    except ClientError:
        return {}
    if not stacks:
        return {}
    out: dict[str, str] = {}
    for item in stacks[0].get("Outputs") or []:
        key = str(item.get("OutputKey") or "").strip()
        val = item.get("OutputValue")
        if key and val is not None:
            out[key] = str(val)
    return out


def _route_from_outputs(
    extensions: list[str],
    outputs: dict[str, str],
    region: str,
    account: str,
) -> dict[str, Any]:
    fn = _output(outputs, "HandlersLambdaFunctionName")
    if not fn:
        return {}
    route = {
        "lambda_function_name": fn,
        "lambda_arn": f"arn:aws:lambda:{region}:{account}:function:{fn}",
        "ecs_cluster": _output(outputs, "HandlersEcsClusterName"),
        "ecs_task_definition": _output(outputs, "HandlersTaskFamily"),
        "ecs_results_bucket": _output(outputs, "HandlersResultsBucketName"),
        "region": region,
    }
    return {ext: dict(route) for ext in extensions}


def _put_ssm(name: str, payload: dict[str, Any], region: str, *, dry_run: bool) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if dry_run:
        print(f"[dry-run] {name} ({len(body)} bytes)")
        return
    import boto3

    boto3.client("ssm", region_name=region).put_parameter(
        Name=name, Value=body, Type="String", Overwrite=True
    )
    print(f"wrote {name}")


def _merge_platform_vars(path: str, peer_map_json: str, region: str, *, dry_run: bool) -> None:
    import boto3
    from botocore.exceptions import ClientError

    ssm = boto3.client("ssm", region_name=region)
    try:
        raw = ssm.get_parameter(Name=path, WithDecryption=True)["Parameter"]["Value"]
        data = json.loads(raw)
    except ClientError:
        print(f"skip merge {path} (missing)")
        return
    vars_block = data.setdefault("VARS", {})
    if not isinstance(vars_block, dict):
        vars_block = {}
        data["VARS"] = vars_block
    vars_block["EXTERNAL_HANDLERS_PEER_MAP"] = peer_map_json
    _put_ssm(path, data, region, dry_run=dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description="Write SSM peer routes from peer stack outputs")
    parser.add_argument("targets_file", help="deploy_targets.yml")
    parser.add_argument("--env-name", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--account", default="")
    parser.add_argument("--peer-id", default="", help="Single peer; default all catalog peers")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    import yaml

    data = yaml.safe_load(Path(args.targets_file).read_text(encoding="utf-8")) or {}
    peers = load_peers(data)
    if args.peer_id:
        peers = [p for p in peers if p["id"] == args.peer_id]
        if not peers:
            print(f"unknown peer {args.peer_id!r}", file=sys.stderr)
            return 1

    account = args.account.strip()
    if not account:
        import boto3

        account = boto3.client("sts", region_name=args.region).get_caller_identity()["Account"]

    merged: dict[str, Any] = {}
    for peer in peers:
        region = peer["aws_region"] or args.region
        stack = peer_stack_name(args.env_name, peer["id"])
        outputs = _cfn_outputs(stack, region)
        if not outputs:
            print(f"skip {stack} (no outputs)")
            continue
        route = _route_from_outputs(peer["extensions"], outputs, region, account)
        if not route:
            print(
                f"skip {stack} (no HandlersLambdaFunctionName output)",
                file=sys.stderr,
            )
            continue
        merged.update(route)
        print(f"mapped {stack} → {','.join(peer['extensions'])}")

    routes_path = f"/{args.env_name}/bootstrap/peer-routes"
    _put_ssm(routes_path, {"routes": merged}, args.region, dry_run=args.dry_run)
    peer_json = json.dumps(merged, separators=(",", ":"), sort_keys=True) if merged else ""
    for stage in ("staging", "production"):
        _merge_platform_vars(
            f"/{args.env_name}/bootstrap/platform-vars/{stage}",
            peer_json,
            args.region,
            dry_run=args.dry_run,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
