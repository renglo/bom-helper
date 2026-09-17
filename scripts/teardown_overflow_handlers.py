#!/usr/bin/env python3
"""Tear down the overflow handlers node after peer smoke is green.

Default is dry-run. Live delete requires both ``--execute`` and
``CONFIRM_OVERFLOW_TEARDOWN=yes``.

Does **not** delete peer stacks (``{env}-peer-{peerId}``), Stack A, or
Stack B API/websocket.

AWS overflow resources (when --execute):

  * Lambda ``{env}-handlers`` and log group ``/aws/lambda/{env}-handlers``
  * ECS cluster ``{env}-handlers``, task family ``{env}-handlers-ecs``
  * ECR ``{env}-handlers-ecs``
  * S3 ``{env}-handlers-ecs-{account}``
  * IAM overflow roles/policy (not ``{env}-peer-{peerId}-*``)

SSM: strips singleton overflow keys from platform-vars after peers are the
only route. Stack B ComputeStack peel and extensions-service archive are
documented in docs/OVERFLOW_TEARDOWN.md — they are git changes, not this script.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

OVERFLOW_LAMBDA_SUFFIX = "-handlers"


def overflow_names(env_name: str, account: str) -> dict[str, str]:
    env = env_name.strip()
    return {
        "lambda": f"{env}-handlers",
        "lambda_log": f"/aws/lambda/{env}-handlers",
        "cluster": f"{env}-handlers",
        "task_family": f"{env}-handlers-ecs",
        "ecr": f"{env}-handlers-ecs",
        "bucket": f"{env}-handlers-ecs-{account}",
        "lambda_role": f"{env}-handlers-role",
        "ecs_exec_role": f"{env}-handlers-ecs-execution",
        "ecs_task_role": f"{env}-handlers-ecs-task",
        "policy": f"{env[0].upper()}{env[1:]}HandlersPolicy",
        "oidc_staging": f"GitHubActionsHandlersRole-{env}-staging",
        "oidc_production": f"GitHubActionsHandlersRole-{env}-production",
    }


def is_overflow_lambda(env_name: str, function_name: str) -> bool:
    """True for ``{env}-handlers``; false for peer Lambdas (``{env}-peer-{peerId}``)."""
    return function_name.strip() == f"{env_name.strip()}{OVERFLOW_LAMBDA_SUFFIX}"


def _delete_lambda(names: dict[str, str], region: str, execute: bool) -> None:
    fn = names["lambda"]
    print(f"Lambda {fn}")
    if not execute:
        return
    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("lambda", region_name=region)
    try:
        client.delete_function(FunctionName=fn)
        print(f"  deleted {fn}")
    except ClientError as exc:
        print(f"  skip {fn}: {exc}")
    logs = boto3.client("logs", region_name=region)
    try:
        logs.delete_log_group(logGroupName=names["lambda_log"])
        print(f"  deleted {names['lambda_log']}")
    except ClientError as exc:
        print(f"  skip log group: {exc}")


def _delete_ecs(names: dict[str, str], region: str, execute: bool) -> None:
    print(f"ECS cluster {names['cluster']} family {names['task_family']}")
    if not execute:
        return
    import boto3
    from botocore.exceptions import ClientError

    ecs = boto3.client("ecs", region_name=region)
    try:
        arns = ecs.list_task_definitions(familyPrefix=names["task_family"]).get("taskDefinitionArns") or []
        for arn in arns:
            ecs.deregister_task_definition(taskDefinition=arn)
            print(f"  deregistered {arn}")
    except ClientError as exc:
        print(f"  skip task defs: {exc}")
    try:
        ecs.delete_cluster(cluster=names["cluster"])
        print(f"  deleted cluster {names['cluster']}")
    except ClientError as exc:
        print(f"  skip cluster: {exc}")


def _delete_ecr_s3_iam(names: dict[str, str], region: str, account: str, execute: bool) -> None:
    print(f"ECR {names['ecr']}  S3 {names['bucket']}")
    if not execute:
        return
    import boto3
    from botocore.exceptions import ClientError

    ecr = boto3.client("ecr", region_name=region)
    try:
        ecr.delete_repository(repositoryName=names["ecr"], force=True)
        print(f"  deleted ECR {names['ecr']}")
    except ClientError as exc:
        print(f"  skip ECR: {exc}")
    s3 = boto3.client("s3", region_name=region)
    try:
        # Best-effort empty + delete
        paginator = s3.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=names["bucket"]):
            objs = []
            for key in ("Versions", "DeleteMarkers"):
                for obj in page.get(key) or []:
                    entry: dict[str, Any] = {"Key": obj["Key"]}
                    if obj.get("VersionId"):
                        entry["VersionId"] = obj["VersionId"]
                    objs.append(entry)
            if objs:
                s3.delete_objects(Bucket=names["bucket"], Delete={"Objects": objs})
        s3.delete_bucket(Bucket=names["bucket"])
        print(f"  deleted bucket {names['bucket']}")
    except ClientError as exc:
        print(f"  skip bucket: {exc}")
    iam = boto3.client("iam")
    for role in (names["lambda_role"], names["ecs_exec_role"], names["ecs_task_role"]):
        try:
            attached = iam.list_attached_role_policies(RoleName=role).get("AttachedPolicies") or []
            for pol in attached:
                iam.detach_role_policy(RoleName=role, PolicyArn=pol["PolicyArn"])
            inlines = iam.list_role_policies(RoleName=role).get("PolicyNames") or []
            for pname in inlines:
                iam.delete_role_policy(RoleName=role, PolicyName=pname)
            iam.delete_role(RoleName=role)
            print(f"  deleted role {role}")
        except ClientError as exc:
            print(f"  skip role {role}: {exc}")
    policy_arn = f"arn:aws:iam::{account}:policy/{names['policy']}"
    try:
        iam.delete_policy(PolicyArn=policy_arn)
        print(f"  deleted policy {policy_arn}")
    except ClientError as exc:
        print(f"  skip policy: {exc}")
    for role in (names["oidc_staging"], names["oidc_production"]):
        try:
            attached = iam.list_attached_role_policies(RoleName=role).get("AttachedPolicies") or []
            for pol in attached:
                iam.detach_role_policy(RoleName=role, PolicyArn=pol["PolicyArn"])
            inlines = iam.list_role_policies(RoleName=role).get("PolicyNames") or []
            for pname in inlines:
                iam.delete_role_policy(RoleName=role, PolicyName=pname)
            iam.delete_role(RoleName=role)
            print(f"  deleted OIDC role {role}")
        except ClientError as exc:
            print(f"  skip OIDC {role}: {exc}")


def _strip_ssm_overflow(env_name: str, region: str, execute: bool) -> None:
    keys = (
        "LAMBDA_EXTERNAL_HANDLERS_ARN",
        "LAMBDA_HANDLERS_FUNCTION_NAME",
        "ECS_CLUSTER",
        "ECS_TASK_DEFINITION",
        "ECS_RESULTS_BUCKET",
        "EXTERNAL_HANDLERS_PEER_ROUTING",
    )
    print(f"SSM strip overflow keys from /{env_name}/bootstrap/platform-vars/* : {', '.join(keys)}")
    if not execute:
        return
    import boto3
    from botocore.exceptions import ClientError

    ssm = boto3.client("ssm", region_name=region)
    for stage in ("staging", "production"):
        name = f"/{env_name}/bootstrap/platform-vars/{stage}"
        try:
            raw = ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
            data = json.loads(raw)
        except ClientError as exc:
            print(f"  skip {name}: {exc}")
            continue
        vars_block = data.get("VARS")
        if not isinstance(vars_block, dict):
            continue
        for key in keys:
            vars_block.pop(key, None)
        ssm.put_parameter(Name=name, Value=json.dumps(data, indent=2, sort_keys=True) + "\n", Type="String", Overwrite=True)
        print(f"  updated {name}")
    for extra in (
        f"/{env_name}/bootstrap/ecs-vpc",
        f"/{env_name}/bootstrap/ecs-subnets",
        f"/{env_name}/bootstrap/ecs-security-groups",
    ):
        try:
            ssm.delete_parameter(Name=extra)
            print(f"  deleted {extra}")
        except ClientError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Tear down overflow {env}-handlers after peer cutover")
    parser.add_argument("--env-name", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--execute", action="store_true", help="Perform deletes (also needs CONFIRM_OVERFLOW_TEARDOWN=yes)")
    args = parser.parse_args()

    names = overflow_names(args.env_name, args.account)
    print("Overflow teardown plan (will not touch peer stacks):")
    for key, value in names.items():
        print(f"  {key}: {value}")

    execute = bool(args.execute) and os.environ.get("CONFIRM_OVERFLOW_TEARDOWN", "").strip() == "yes"
    if args.execute and not execute:
        print("Refusing --execute without CONFIRM_OVERFLOW_TEARDOWN=yes", file=sys.stderr)
        return 2
    if not execute:
        print("dry-run only (pass --execute and CONFIRM_OVERFLOW_TEARDOWN=yes to delete)")

    _delete_lambda(names, args.region, execute)
    _delete_ecs(names, args.region, execute)
    _delete_ecr_s3_iam(names, args.region, args.account, execute)
    _strip_ssm_overflow(args.env_name, args.region, execute)
    print("Done. Peel Stack B ComputeStack and archive extensions-service per docs/OVERFLOW_TEARDOWN.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
