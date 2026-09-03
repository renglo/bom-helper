#!/usr/bin/env python3
"""Read deploy_targets.yml and print JSON suitable for matrix.fromJson.

Nested schema:
  tenants:
    <tenant_key>:
      id: <aws_prefix>
      aws_account: "..."
      aws_region: us-east-1   # optional
      stages:
        staging: { enabled: true }
        production: { enabled: true }

Pipelines:
  backend / console — one row per (tenant, stage) with OIDC + SSM fields.
  handlers — one row per tenant (deploy_stage from handlers_bom JSON).

Flags:
  --build-bom           print backend BOM version only
  --handlers-bom        print handlers BOM version only
  --filter-json PATH    intersect with another matrix/filter JSON
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

VALID_STAGES = ("staging", "production")
VALID_HANDLERS_COMPUTE = ("ecs", "lambda_only")
DEFAULT_HANDLERS_COMPUTE = "ecs"
DEFAULT_AWS_REGION = "us-east-1"
OIDC_ROLE_TEMPLATE = "arn:aws:iam::{account}:role/GitHubActionsDeployRole-{id}-{stage}"
OIDC_HANDLERS_ROLE_TEMPLATE = (
    "arn:aws:iam::{account}:role/GitHubActionsHandlersRole-{id}-{stage}"
)
PLATFORM_VARS_SSM_TEMPLATE = "/{id}/bootstrap/platform-vars/{stage}"
DEPLOY_INPUT_SSM_TEMPLATE = "/{id}/bootstrap/deploy-input"
DEFAULT_REGISTRY = {
    "domain": "renglo",
    "python_repository": "python-store",
    "npm_repository": "npm-store",
}


def _latest_bom(bom_dir: Path) -> str:
    files = list(bom_dir.glob("v*.json"))
    if not files:
        raise RuntimeError(f"No BOM files found in {bom_dir}")
    versions: list[tuple[tuple[int, ...], str]] = []
    for f in files:
        m = re.match(r"v(\d+\.\d+\.\d+)\.json$", f.name)
        if m:
            versions.append((tuple(int(x) for x in m.group(1).split(".")), m.group(1)))
    if not versions:
        raise RuntimeError(f"No versioned BOM files (vX.Y.Z.json) found in {bom_dir}")
    versions.sort(reverse=True)
    return versions[0][1]


def resolve_build_bom(data: dict, bom_dir: Path) -> str:
    root = str(data.get("bom", "")).strip()
    if root:
        return root
    return _latest_bom(bom_dir)


def resolve_handlers_bom(data: dict, handlers_dir: Path) -> str:
    root = str(data.get("handlers_bom", "")).strip()
    if root:
        return root
    return _latest_bom(handlers_dir)


def resolve_registry(data: dict) -> dict[str, str]:
    """Publisher CodeArtifact connection for pip/npm login.

    ``registry.domain_owner`` and ``registry.region`` default to the first
    tenant account/region when omitted (same-account publisher + tenant).
    """
    raw = data.get("registry") or {}
    if not isinstance(raw, dict):
        raise RuntimeError("deploy_targets.yml: registry must be a mapping")

    domain = str(raw.get("domain") or DEFAULT_REGISTRY["domain"]).strip() or DEFAULT_REGISTRY["domain"]
    python_repository = (
        str(raw.get("python_repository") or DEFAULT_REGISTRY["python_repository"]).strip()
        or DEFAULT_REGISTRY["python_repository"]
    )
    npm_repository = (
        str(raw.get("npm_repository") or DEFAULT_REGISTRY["npm_repository"]).strip()
        or DEFAULT_REGISTRY["npm_repository"]
    )
    owner = str(raw.get("domain_owner") or "").strip()
    region = str(raw.get("region") or "").strip()

    tenants = data.get("tenants") or {}
    if isinstance(tenants, dict):
        for tenant_cfg in tenants.values():
            if not isinstance(tenant_cfg, dict):
                continue
            if not owner:
                owner = str(tenant_cfg.get("aws_account") or "").strip()
            if not region:
                region = str(tenant_cfg.get("aws_region") or "").strip()
            if owner and region:
                break

    if not owner:
        raise RuntimeError(
            "deploy_targets.yml: set registry.domain_owner or tenants.*.aws_account"
        )
    return {
        "domain": domain,
        "domain_owner": owner,
        "python_repository": python_repository,
        "npm_repository": npm_repository,
        "region": region or DEFAULT_AWS_REGION,
    }


def resolve_handlers_compute(data: dict) -> str:
    raw = str(data.get("handlers_compute", DEFAULT_HANDLERS_COMPUTE)).strip().lower()
    if not raw:
        return DEFAULT_HANDLERS_COMPUTE
    if raw not in VALID_HANDLERS_COMPUTE:
        raise RuntimeError(
            f"Invalid handlers_compute: {raw!r} (expected {', '.join(VALID_HANDLERS_COMPUTE)})"
        )
    return raw


def _oidc_role_arn(account: str, env_id: str, stage: str) -> str:
    return OIDC_ROLE_TEMPLATE.format(account=account, id=env_id, stage=stage)


def _oidc_handlers_role_arn(account: str, env_id: str, stage: str) -> str:
    return OIDC_HANDLERS_ROLE_TEMPLATE.format(account=account, id=env_id, stage=stage)


def _platform_vars_parameter(env_id: str, stage: str) -> str:
    return PLATFORM_VARS_SSM_TEMPLATE.format(id=env_id, stage=stage)


def _deploy_input_parameter(env_id: str) -> str:
    return DEPLOY_INPUT_SSM_TEMPLATE.format(id=env_id)


def _stage_enabled(stage_cfg: Any) -> bool:
    if stage_cfg is True:
        return True
    if isinstance(stage_cfg, dict):
        return stage_cfg.get("enabled", True) is not False
    return False


def _load_handlers_deploy_stage(handlers_dir: Path, version: str) -> str:
    path = handlers_dir / f"v{version}.json"
    if not path.is_file():
        raise RuntimeError(f"Handlers BOM file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    stage = str(data.get("deploy_stage", "production")).strip().lower()
    if stage not in VALID_STAGES:
        raise RuntimeError(f"Invalid deploy_stage in {path}: {stage!r}")
    return stage


def _iter_tenant_stages(data: dict) -> list[dict[str, Any]]:
    tenants_raw = data.get("tenants") or {}
    if not isinstance(tenants_raw, dict):
        raise RuntimeError("deploy_targets.yml: tenants must be a mapping")

    rows: list[dict[str, Any]] = []
    for tenant_key, tenant_cfg in tenants_raw.items():
        if not isinstance(tenant_cfg, dict):
            continue
        tenant = str(tenant_key).strip()
        env_id = str(tenant_cfg.get("id", "")).strip()
        account = str(tenant_cfg.get("aws_account", "")).strip()
        region = str(tenant_cfg.get("aws_region", DEFAULT_AWS_REGION)).strip() or DEFAULT_AWS_REGION
        stages = tenant_cfg.get("stages") or {}
        if not tenant or not env_id or not account or not isinstance(stages, dict):
            print(f"Skipping invalid tenant config: {tenant_key!r}")
            continue

        for stage_name, stage_cfg in stages.items():
            stage = str(stage_name).strip().lower()
            if stage not in VALID_STAGES:
                continue
            if not _stage_enabled(stage_cfg):
                continue
            rows.append(
                {
                    "tenant": tenant,
                    "stage": stage,
                    "id": env_id,
                    "aws_account": account,
                    "aws_region": region,
                    "oidc_role_arn": _oidc_role_arn(account, env_id, stage),
                    "ssm_parameter": _platform_vars_parameter(env_id, stage),
                }
            )
    return rows


def _handlers_rows(data: dict, repo_root: Path) -> list[dict[str, Any]]:
    handlers_dir = repo_root / "handlers_bom"
    handlers_version = resolve_handlers_bom(data, handlers_dir)
    deploy_stage = _load_handlers_deploy_stage(handlers_dir, handlers_version)
    handlers_compute = resolve_handlers_compute(data)

    tenants_raw = data.get("tenants") or {}
    if not isinstance(tenants_raw, dict):
        raise RuntimeError("deploy_targets.yml: tenants must be a mapping")

    rows: list[dict[str, Any]] = []
    for tenant_key, tenant_cfg in tenants_raw.items():
        if not isinstance(tenant_cfg, dict):
            continue
        tenant = str(tenant_key).strip()
        env_id = str(tenant_cfg.get("id", "")).strip()
        account = str(tenant_cfg.get("aws_account", "")).strip()
        region = str(tenant_cfg.get("aws_region", DEFAULT_AWS_REGION)).strip() or DEFAULT_AWS_REGION
        stages = tenant_cfg.get("stages") or {}
        if not tenant or not env_id or not account:
            continue
        if not isinstance(stages, dict):
            continue
        if not any(_stage_enabled(cfg) for cfg in stages.values()):
            continue

        rows.append(
            {
                "tenant": tenant,
                "id": env_id,
                "aws_account": account,
                "aws_region": region,
                "deploy_stage": deploy_stage,
                "handlers_bom": handlers_version,
                "handlers_compute": handlers_compute,
                "oidc_role_arn": _oidc_handlers_role_arn(account, env_id, deploy_stage),
                "ssm_parameter": _deploy_input_parameter(env_id),
            }
        )
    return rows


def _apply_filter(rows: list[dict[str, Any]], filter_path: Path, pipeline: str) -> list[dict[str, Any]]:
    if not filter_path.is_file():
        return rows
    filt = json.loads(filter_path.read_text(encoding="utf-8"))
    allowed = filt.get("include") or []
    if not allowed:
        return []

    if pipeline == "handlers":
        tenants = {str(x.get("tenant", "")).strip() for x in allowed if isinstance(x, dict)}
        return [r for r in rows if r.get("tenant") in tenants]

    keys = {
        (str(x.get("tenant", "")).strip(), str(x.get("stage", "")).strip().lower())
        for x in allowed
        if isinstance(x, dict)
    }
    return [r for r in rows if (r.get("tenant"), r.get("stage")) in keys]


def main() -> int:
    parser = argparse.ArgumentParser(description="Render deploy matrix from deploy_targets.yml")
    parser.add_argument("targets_file", help="Path to deploy_targets.yml")
    parser.add_argument(
        "--pipeline",
        choices=("backend", "console", "handlers"),
        default="backend",
        help="Matrix shape and filters",
    )
    parser.add_argument("--stage", choices=VALID_STAGES, default="", help="Optional stage filter (backend/console)")
    parser.add_argument("--build-bom", action="store_true", help="Print backend BOM version only")
    parser.add_argument("--handlers-bom", action="store_true", help="Print handlers BOM version only")
    parser.add_argument("--registry", action="store_true", help="Print CodeArtifact registry JSON")
    parser.add_argument("--filter-json", default="", help="Intersect with filter JSON (include list)")
    args = parser.parse_args()

    path = Path(args.targets_file)
    if not path.is_file():
        print(f"File not found: {path}")
        return 1

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    repo_root = path.parent

    if args.build_bom:
        print(resolve_build_bom(data, repo_root / "bom"))
        return 0
    if args.handlers_bom:
        print(resolve_handlers_bom(data, repo_root / "handlers_bom"))
        return 0
    if args.registry:
        print(json.dumps(resolve_registry(data), separators=(",", ":")))
        return 0

    if args.pipeline == "handlers":
        rows = _handlers_rows(data, repo_root)
    else:
        rows = _iter_tenant_stages(data)
        if args.stage:
            rows = [r for r in rows if r.get("stage") == args.stage]

    if args.filter_json:
        rows = _apply_filter(rows, Path(args.filter_json), args.pipeline)

    print(json.dumps({"include": rows}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
