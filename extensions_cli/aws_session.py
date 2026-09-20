from __future__ import annotations

import os
from typing import Any

from extensions_cli.errors import ExtensionsError
from extensions_cli.workspace import load_customer_config


def resolve_aws(
    sheet: dict[str, Any] | None,
    workspace,
    *,
    require_sheet: bool = False,
) -> tuple[str, str]:
    """Profile from incubation sheet (preferred) or AWS_PROFILE. Region from sheet or config."""
    profile = ""
    region = ""
    if sheet:
        profile = str(sheet.get("aws_profile") or "").strip()
        region = str(sheet.get("aws_region") or "").strip()
    if not profile:
        profile = os.environ.get("AWS_PROFILE", "").strip()
    if require_sheet and sheet and not str(sheet.get("aws_profile") or "").strip():
        raise ExtensionsError(
            "incubation sheet has no aws_profile — run install place with --profile"
        )
    if not profile:
        raise ExtensionsError(
            "AWS profile required — pass --profile on install place (stored on the sheet)"
        )
    if not region:
        cfg = load_customer_config(workspace)
        region = str(cfg.get("aws_region") or "us-east-1").strip() or "us-east-1"
    return profile, region


def apply_to_env(profile: str, region: str) -> None:
    os.environ["AWS_PROFILE"] = profile
    os.environ.setdefault("AWS_REGION", region)
