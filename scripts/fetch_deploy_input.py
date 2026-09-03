#!/usr/bin/env python3
"""Fetch deploy config from SSM and optionally merge repo secrets / export env."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# Keys never merged into Lambda runtime from deploy input.
CI_ONLY_ENV_PREFIXES = ("CODEDEPLOY_", "AWS_GITHUB_", "AWS_ECR_")
CI_ONLY_ENV_KEYS = frozenset(
    {
        "AWS_ECR_REPOSITORY",
        "LAMBDA_BACKEND_ARN",
        "AWS_GITHUB_OIDC_ROLE_ARN",
    }
)
RESERVED_LAMBDA_ENV_KEYS = frozenset(
    {
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_EXECUTION_ENV",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    }
)


def _is_reserved_env_key(key: str) -> bool:
    k = key.strip()
    if not k or k in RESERVED_LAMBDA_ENV_KEYS or k in CI_ONLY_ENV_KEYS:
        return True
    if k.startswith("AWS_LAMBDA_"):
        return True
    for prefix in CI_ONLY_ENV_PREFIXES:
        if k.startswith(prefix):
            return True
    return False


def _fetch_ssm_value(name: str, region: str) -> str:
    try:
        import boto3
    except ImportError:
        boto3 = None  # type: ignore

    if boto3 is not None:
        client = boto3.client("ssm", region_name=region)
        resp = client.get_parameter(Name=name, WithDecryption=True)
        return str(resp["Parameter"]["Value"])

    proc = subprocess.run(
        [
            "aws",
            "ssm",
            "get-parameter",
            "--name",
            name,
            "--with-decryption",
            "--region",
            region,
            "--output",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return str(json.loads(proc.stdout)["Parameter"]["Value"])


def _fetch_ssm_json(name: str, region: str) -> dict[str, Any]:
    raw = _fetch_ssm_value(name, region)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"SSM parameter {name} must contain a JSON object")
    return data


def _merge_secrets(payload: dict[str, Any], secret_specs: list[str]) -> None:
    secrets = payload.setdefault("SECRETS", {})
    if not isinstance(secrets, dict):
        secrets = {}
        payload["SECRETS"] = secrets
    for spec in secret_specs:
        if "=" in spec:
            key, env_name = spec.split("=", 1)
        else:
            key, env_name = spec, spec
        val = os.environ.get(env_name.strip(), "").strip()
        if val:
            secrets[key.strip()] = val


def _merge_var_from_ssm(
    payload: dict[str, Any],
    var_key: str,
    parameter_name: str,
    region: str,
) -> None:
    val = _fetch_ssm_value(parameter_name, region).strip()
    if not val:
        return
    vars_block = payload.setdefault("VARS", {})
    if not isinstance(vars_block, dict):
        vars_block = {}
        payload["VARS"] = vars_block
    vars_block[var_key] = val


def _runtime_env(payload: dict[str, Any], stage: str = "") -> dict[str, str]:
    vars_block = payload.get("VARS") or {}
    secrets_block = payload.get("SECRETS") or {}
    if not isinstance(vars_block, dict):
        vars_block = {}
    if not isinstance(secrets_block, dict):
        secrets_block = {}

    merged: dict[str, str] = {}
    for src in (vars_block, secrets_block):
        for k, v in src.items():
            if v is None:
                continue
            s = str(v).strip()
            if s:
                merged[str(k)] = s

    if "FE_BASE_URL" not in merged and merged.get("AMPLIFY_CONSOLE_URL"):
        merged["FE_BASE_URL"] = merged["AMPLIFY_CONSOLE_URL"]
    if stage and "SYS_ENV" not in merged:
        merged["SYS_ENV"] = stage
    elif not stage and "SYS_ENV" not in merged and merged.get("ENVIRONMENT"):
        merged["SYS_ENV"] = merged["ENVIRONMENT"]

    return {k: v for k, v in merged.items() if not _is_reserved_env_key(k)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch deploy config from SSM Parameter Store")
    parser.add_argument(
        "--parameter",
        required=True,
        help="Primary SSM parameter (JSON: platform-vars or deploy-input)",
    )
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--output", default="", help="Write full deploy_input JSON to this path")
    parser.add_argument(
        "--merge-secret",
        action="append",
        default=[],
        help="Merge env var into SECRETS (KEY or KEY=ENV_NAME); repeatable",
    )
    parser.add_argument(
        "--merge-parameter",
        action="append",
        default=[],
        help="Merge plain SSM string into VARS (VAR_KEY=/ssm/path); repeatable",
    )
    parser.add_argument("--export-env", default="", help="Write shell KEY=value lines (one per line)")
    parser.add_argument(
        "--export-lambda-merge",
        default="",
        help="Write lambda_env_merge.json for deploy_lambda_codedeploy.py",
    )
    parser.add_argument("--stage", default="", help="Stage label for SYS_ENV when exporting lambda merge")
    args = parser.parse_args()

    payload = _fetch_ssm_json(args.parameter, args.region)
    if args.merge_secret:
        _merge_secrets(payload, args.merge_secret)
    for spec in args.merge_parameter:
        if "=" not in spec:
            print(f"Invalid --merge-parameter (expected VAR_KEY=/ssm/path): {spec!r}", file=sys.stderr)
            return 1
        var_key, param_name = spec.split("=", 1)
        var_key = var_key.strip()
        param_name = param_name.strip()
        if not var_key or not param_name:
            print(f"Invalid --merge-parameter: {spec!r}", file=sys.stderr)
            return 1
        _merge_var_from_ssm(payload, var_key, param_name, args.region)

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {out}")

    runtime = _runtime_env(payload, stage=args.stage)

    if args.export_env:
        lines = [f"{k}={v}" for k, v in sorted(runtime.items())]
        Path(args.export_env).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Wrote {len(lines)} env vars to {args.export_env}")

    if args.export_lambda_merge:
        Path(args.export_lambda_merge).write_text(
            json.dumps(runtime, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote lambda merge ({len(runtime)} keys) to {args.export_lambda_merge}")

    if not args.output and not args.export_env and not args.export_lambda_merge:
        print(json.dumps(payload, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
