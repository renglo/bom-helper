#!/usr/bin/env python3
"""CDK app: one CloudFormation stack per catalog peer.

Peer laptop deploy shares configuration with bootstrap/launcher:
``launcher/cdk/customer-config.json`` supplies ``env_name`` and ``github_repo``
(BOM git id for OIDC). The *-bom catalog comes from sibling ``*-bom/deploy_targets.yml``.

Optional overrides (see docs/PEERS.md):
  peer_id          omit to synth/deploy every catalog peer
  tenant / env_name / bom_repo / bom_checkout / targets

Stack name: ``{env}-peer-{peerId}``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from aws_cdk import App, Environment, Stack
from aws_cdk import aws_iam as iam

_CDK_DIR = Path(__file__).resolve().parent
_HELPER_ROOT = _CDK_DIR.parent
sys.path.insert(0, str(_CDK_DIR))
sys.path.insert(0, str(_HELPER_ROOT / "scripts"))

from compute_stack import ComputeStack  # noqa: E402
from peer_deploy_context import load_targets_yaml, resolve_peer_deploy_context  # noqa: E402
from peers import load_peers, peer_stack_name  # noqa: E402
from targets import ctx_get as _ctx  # noqa: E402


def _tenant_cfg(data: dict, tenant_key: str, env_name: str) -> dict:
    tenants = data.get("tenants") or {}
    if tenant_key and tenant_key in tenants and isinstance(tenants[tenant_key], dict):
        return tenants[tenant_key]
    for cfg in tenants.values():
        if isinstance(cfg, dict) and str(cfg.get("id", "")).strip() == env_name:
            return cfg
    raise SystemExit(f"No tenant with id={env_name!r} (or key={tenant_key!r}) in deploy_targets.yml")


class HandlersPeerStack(Stack):
    def __init__(
        self,
        scope: App,
        stack_id: str,
        *,
        env_name: str,
        peer: dict,
        github_handlers_repo: str,
        github_handlers_owner_id: str | None = None,
        github_handlers_repo_id: str | None = None,
        aws_account: str,
        aws_region: str,
        enable_staging: bool,
        **kwargs,
    ) -> None:
        super().__init__(scope, stack_id, **kwargs)
        compute_type = str(peer["compute"])
        ComputeStack(
            self,
            "Compute",
            env_name=env_name,
            aws_account=aws_account,
            aws_region=aws_region,
            compute_type=compute_type,
            peer_id=str(peer["id"]),
            task_size=str(peer.get("task_size") or "medium"),
            ec2_instance_type=str(peer.get("ec2_instance_type") or "t3.medium"),
            ec2_min_instances=int(peer.get("ec2_min_instances") or 0),
            ec2_desired_instances=int(peer.get("ec2_desired_instances") or 1),
            ec2_max_instances=int(peer.get("ec2_max_instances") or 2),
            github_handlers_repo=github_handlers_repo,
            github_handlers_owner_id=github_handlers_owner_id,
            github_handlers_repo_id=github_handlers_repo_id,
            enable_staging=enable_staging,
            tenant_policy=iam.ManagedPolicy.from_managed_policy_name(
                self,
                "ImportedTenantPolicy",
                managed_policy_name=f"{env_name}_tt_policy",
            ),
        )


def main() -> None:
    app = App()
    ctx = resolve_peer_deploy_context(
        helper_root=_HELPER_ROOT,
        tenant=_ctx(app, "tenant", "PEER_TENANT"),
        env_name=_ctx(app, "env_name", "PEER_ENV_NAME") or _ctx(app, "env", "ENV"),
        bom_repo=_ctx(app, "bom_repo", "BOM_REPO"),
        bom_checkout=_ctx(app, "bom_checkout", "BOM_CHECKOUT"),
        targets=_ctx(app, "targets", "PEER_TARGETS"),
    )
    tenant_key = ctx["tenant"]
    env_name = ctx["env_name"]
    bom_repo = ctx["bom_repo"]
    targets_path = Path(ctx["targets_path"])

    data = load_targets_yaml(targets_path)
    peers = load_peers(data)
    if not peers:
        raise SystemExit(f"No peers: catalog in {targets_path}")

    tenant = _tenant_cfg(data, tenant_key, env_name)
    aws_account = _ctx(app, "aws_account", "CDK_DEFAULT_ACCOUNT") or str(
        tenant.get("aws_account", "")
    ).strip()
    aws_region = _ctx(app, "aws_region", "CDK_DEFAULT_REGION") or str(
        tenant.get("aws_region", "us-east-1")
    ).strip()
    want_peer = _ctx(app, "peer_id", "PEER_ID")
    stages = tenant.get("stages") or {}
    enable_staging = True
    if isinstance(stages, dict) and isinstance(stages.get("staging"), dict):
        enable_staging = stages["staging"].get("enabled", True) is not False

    selected = [p for p in peers if not want_peer or p["id"] == want_peer]
    if not selected:
        raise SystemExit(f"peer_id {want_peer!r} not in catalog")

    for peer in selected:
        region = str(peer.get("aws_region") or aws_region)
        peer_env = Environment(account=aws_account, region=region)
        stack_name = peer_stack_name(env_name, peer["id"])
        HandlersPeerStack(
            app,
            stack_name,
            stack_name=stack_name,
            env=peer_env,
            env_name=env_name,
            peer=peer,
            github_handlers_repo=bom_repo,
            github_handlers_owner_id=ctx.get("github_owner_id") or None,
            github_handlers_repo_id=ctx.get("github_repo_id") or None,
            aws_account=aws_account,
            aws_region=region,
            enable_staging=enable_staging,
        )

    app.synth()


if __name__ == "__main__":
    main()
