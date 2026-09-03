#!/usr/bin/env python3
"""Deploy a Lambda container image using CodeDeploy (Lambda deployment group).

Sequence (per BOM deploy pipeline):
  1. lambda:UpdateFunctionCode with Publish=False ($LATEST gets new image)
  2. Optionally lambda:UpdateFunctionConfiguration to merge env vars from JSON
  3. Wait until function is Active / LastUpdateStatus Successful
  4. lambda:PublishVersion -> immutable version number
  5. codedeploy:CreateDeployment with AppSpecContent shifting alias traffic

Requires an existing Lambda alias (e.g. staging / production) and CodeDeploy application + deployment group.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import boto3

# Keys Lambda rejects or that should never be set from CI merge (see also renglo schd external_handler_runner).
RESERVED_LAMBDA_ENV_KEYS = frozenset(
    {
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_EXECUTION_ENV",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_SECURITY_TOKEN",
        "AWS_LAMBDA_FUNCTION_NAME",
        "AWS_LAMBDA_FUNCTION_VERSION",
        "AWS_LAMBDA_FUNCTION_MEMORY_SIZE",
        "AWS_LAMBDA_LOG_GROUP_NAME",
        "AWS_LAMBDA_LOG_STREAM_NAME",
        "AWS_LAMBDA_RUNTIME_API",
        "AWS_LAMBDA_INITIALIZATION_TYPE",
        "AWS_XRAY_CONTEXT_MISSING",
        "AWS_XRAY_DAEMON_ADDRESS",
    }
)

# Never push GitHub / CodeDeploy / CI-only keys into Lambda environment.
CI_ONLY_ENV_PREFIXES = ("CODEDEPLOY_", "AWS_GITHUB_", "AWS_ECR_")
CI_ONLY_ENV_KEYS = frozenset({"AWS_ECR_REPOSITORY", "LAMBDA_BACKEND_ARN"})


def _is_reserved_env_key(key: str) -> bool:
    k = key.strip()
    if not k:
        return True
    if k in RESERVED_LAMBDA_ENV_KEYS or k in CI_ONLY_ENV_KEYS:
        return True
    if k.startswith("AWS_LAMBDA_"):
        return True
    for prefix in CI_ONLY_ENV_PREFIXES:
        if k.startswith(prefix):
            return True
    return False


def _wait_for_function_updated(lambda_client, function_name: str, timeout_s: int = 600) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        cfg = lambda_client.get_function_configuration(FunctionName=function_name)
        state = cfg.get("State", "")
        last_status = cfg.get("LastUpdateStatus", "")
        if state == "Active" and last_status in ("Successful", ""):
            return
        if last_status == "Failed":
            reason = cfg.get("LastUpdateStatusReason", "")
            raise RuntimeError(f"Lambda update failed: {reason}")
        time.sleep(3)
    raise TimeoutError(f"Timed out waiting for {function_name} to become active")


def _load_env_merge(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        data: Any = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("merge-lambda-env-json must be a JSON object")
    out: dict[str, str] = {}
    for k, v in data.items():
        sk = str(k).strip()
        if _is_reserved_env_key(sk):
            print(f"Skipping reserved/CI-only env key: {sk}", file=sys.stderr)
            continue
        if v is None:
            continue
        out[sk] = str(v)
    return out


def _build_appspec_yaml(*, function_name: str, alias: str, current_version: str, target_version: str) -> str:
    # AWS CodeDeploy Lambda AppSpec (YAML). Property names are case-sensitive per AWS docs.
    return (
        "version: 0.0\n"
        "Resources:\n"
        "  - BackendLambda:\n"
        "      Type: AWS::Lambda::Function\n"
        "      Properties:\n"
        f"        Name: {function_name}\n"
        f"        Alias: {alias}\n"
        f'        CurrentVersion: "{current_version}"\n'
        f'        TargetVersion: "{target_version}"\n'
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Lambda image deploy via CodeDeploy.")
    parser.add_argument("--function-name", required=True)
    parser.add_argument("--image-uri", required=True, help="Full ECR image URI including tag or digest")
    parser.add_argument("--alias-name", required=True, help="Lambda alias CodeDeploy shifts (e.g. staging, production)")
    parser.add_argument("--application-name", required=True)
    parser.add_argument("--deployment-group-name", required=True)
    parser.add_argument("--deployment-config-name", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument(
        "--merge-lambda-env-json",
        default="",
        help="Optional path to JSON object of env vars to merge into Lambda configuration ($LATEST) before PublishVersion",
    )
    parser.add_argument(
        "--wait-deployment-success",
        action="store_true",
        help="Poll codedeploy:GetDeployment until success (or failure)",
    )
    parser.add_argument("--wait-timeout-seconds", type=int, default=1800)
    args = parser.parse_args()

    session = boto3.Session(region_name=args.region)
    lam = session.client("lambda")
    cd = session.client("codedeploy")

    alias_resp = lam.get_alias(FunctionName=args.function_name, Name=args.alias_name)
    current_version = str(alias_resp["FunctionVersion"])

    print(f"Alias {args.alias_name!r} currently on version {current_version}", file=sys.stderr)

    print("UpdateFunctionCode (Publish=False)...", file=sys.stderr)
    lam.update_function_code(FunctionName=args.function_name, ImageUri=args.image_uri, Publish=False)
    _wait_for_function_updated(lam, args.function_name)

    merge = _load_env_merge(args.merge_lambda_env_json or None)
    if merge:
        print(f"UpdateFunctionConfiguration merging {len(merge)} env var(s)...", file=sys.stderr)
        existing = lam.get_function_configuration(FunctionName=args.function_name)
        env_vars: dict[str, str] = dict(existing.get("Environment", {}).get("Variables", {}))
        env_vars.update(merge)
        lam.update_function_configuration(FunctionName=args.function_name, Environment={"Variables": env_vars})
        _wait_for_function_updated(lam, args.function_name)

    print("PublishVersion...", file=sys.stderr)
    pub = lam.publish_version(FunctionName=args.function_name)
    target_version = str(pub["Version"])
    print(f"Published version {target_version}", file=sys.stderr)

    appspec = _build_appspec_yaml(
        function_name=args.function_name,
        alias=args.alias_name,
        current_version=current_version,
        target_version=target_version,
    )

    print("CreateDeployment...", file=sys.stderr)
    dep = cd.create_deployment(
        applicationName=args.application_name,
        deploymentGroupName=args.deployment_group_name,
        deploymentConfigName=args.deployment_config_name,
        revision={"revisionType": "AppSpecContent", "appSpecContent": {"content": appspec}},
        description=f"GitHub Actions deploy {args.function_name} -> {target_version}",
    )
    deployment_id = dep["deploymentId"]
    print(f"deploymentId={deployment_id}", file=sys.stderr)

    if args.wait_deployment_success:
        deadline = time.monotonic() + args.wait_timeout_seconds
        while time.monotonic() < deadline:
            info = cd.get_deployment(deploymentId=deployment_id)
            status = info["deploymentInfo"]["status"]
            if status == "Succeeded":
                print("CodeDeploy deployment Succeeded", file=sys.stderr)
                return 0
            if status in ("Failed", "Stopped"):
                err = info["deploymentInfo"].get("errorInformation", {})
                raise RuntimeError(f"CodeDeploy deployment {status}: {err}")
            time.sleep(10)
        raise TimeoutError(f"Timed out waiting for deployment {deployment_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
