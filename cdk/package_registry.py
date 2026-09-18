"""CodeArtifact reader account resolution for the handlers/peer OIDC role.

Mirrors launcher ``cdk/lib/package_registry.py`` so peer CI can pip-login the
same domains as console/backend (tenant account + ``domain_owners``).
"""

from __future__ import annotations


def codeartifact_owners(account: str, package_registry: dict | None = None) -> list[str]:
    """AWS accounts the deploy role may read CodeArtifact from.

    The tenant account is always included (internal/same-account registries).
    Foreign publisher accounts come only from ``package_registry.domain_owners``.
    """
    owners: list[str] = []
    tenant = str(account or "").strip()
    if tenant:
        owners.append(tenant)

    if package_registry is None:
        return owners
    if not isinstance(package_registry, dict):
        raise ValueError("package_registry must be an object")
    if "domain_owner" in package_registry:
        raise ValueError(
            "package_registry.domain_owner is not supported; use domain_owners (list)"
        )

    raw = package_registry.get("domain_owners", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ValueError("package_registry.domain_owners must be a list of account IDs")
    for item in raw:
        owner = str(item or "").strip()
        if not owner:
            raise ValueError("package_registry.domain_owners entries must be non-empty strings")
        if owner not in owners:
            owners.append(owner)
    return owners


def codeartifact_read_resources(
    region: str,
    account: str,
    package_registry: dict | None = None,
) -> list[str]:
    """IAM resource ARNs for CodeArtifact read (domain / repository / package)."""
    region = str(region or "").strip()
    resources: list[str] = []
    for owner in codeartifact_owners(account, package_registry):
        resources.extend(
            [
                f"arn:aws:codeartifact:{region}:{owner}:domain/*",
                f"arn:aws:codeartifact:{region}:{owner}:repository/*/*",
                f"arn:aws:codeartifact:{region}:{owner}:package/*/*/*/*",
            ]
        )
    return resources
