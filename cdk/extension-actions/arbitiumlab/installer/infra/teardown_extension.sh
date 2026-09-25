#!/usr/bin/env bash
# Tear down AWS resources created by provision_extension.sh (self-contained).
#
# Does not read extra_resources.json or bootstrap state. Uses:
#   - Per-env naming: {env}-threat-events-{account}, {env}_actions_tt_policy
#   - <env_name> for platform role names to detach from
#   - account_id from STS (aws profile)
#
# Removes (in dependency order):
#   1. Detach {env}_actions_tt_policy from {env}_tt_role, {env}-handlers-role,
#      {env}-handlers-ecs-task
#   2. Delete all non-default versions of {env}_actions_tt_policy, then delete policy
#   3. Empty and delete S3 bucket  {env}-threat-events-{account_id}
#
# Usage:
#   ./teardown_extension.sh <env_name> [--aws-profile PROFILE] [--aws-region REGION] [--dry-run]

set -euo pipefail

export AWS_PAGER="${AWS_PAGER:-}"

POLICY_NAME=""
BUCKET_PREFIX=""

ENV_NAME=""
AWS_PROFILE_ARG=""
AWS_REGION="us-east-1"
DRY_RUN=false

usage() {
  echo "Usage: $0 <env_name> [--aws-profile PROFILE] [--aws-region REGION] [--dry-run]" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do

  if [[ "$1" == "--aws-profile" ]]; then
    AWS_PROFILE_ARG="$2"
    shift 2

  elif [[ "$1" == "--aws-region" ]]; then
    AWS_REGION="$2"
    shift 2

  elif [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
    shift

  else
    ENV_NAME="$1"
    shift
  fi

done

[[ -z "$ENV_NAME" ]] && usage

POLICY_NAME="${ENV_NAME}_actions_tt_policy"
BUCKET_PREFIX="${ENV_NAME}-threat-events"

if [[ -n "$AWS_PROFILE_ARG" ]]; then
  export AWS_PROFILE="$AWS_PROFILE_ARG"
  export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"
fi
export AWS_REGION

AWS_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
POLICY_ARN="arn:aws:iam::${AWS_ACCOUNT}:policy/${POLICY_NAME}"
BUCKET_NAME="${BUCKET_PREFIX}-${AWS_ACCOUNT}"

echo "=========================================="
echo "TEARDOWN arbitium extension: $ENV_NAME"
echo "Region: $AWS_REGION   Account: $AWS_ACCOUNT"
[[ -n "${AWS_PROFILE:-}" ]] && echo "AWS Profile: $AWS_PROFILE"
[[ "$DRY_RUN" == "true" ]] && echo "Mode: DRY-RUN (no AWS changes will be made)"
echo "=========================================="
echo ""
echo "Resources to remove:"
echo "  IAM policy:  $POLICY_NAME (detach from ${ENV_NAME}_tt_role, ${ENV_NAME}-handlers-role, ${ENV_NAME}-handlers-ecs-task)"
echo "  S3 bucket:   $BUCKET_NAME"
echo ""

# ── Step 1: Detach policy from roles ─────────────────────────────────────────
echo "==> [1/3] Detach $POLICY_NAME from roles..."

TARGET_ROLES=(
  "${ENV_NAME}_tt_role"
  "${ENV_NAME}-handlers-role"
  "${ENV_NAME}-handlers-ecs-task"
)

for role in "${TARGET_ROLES[@]}"; do
  if ! aws iam get-role --role-name "$role" >/dev/null 2>&1; then
    echo "  Role '$role' not found — skipping"
    continue
  fi

  ATTACHED=$(aws iam list-attached-role-policies --role-name "$role" \
    --query "AttachedPolicies[?PolicyArn=='${POLICY_ARN}'].PolicyArn" \
    --output text 2>/dev/null || true)

  if [[ -z "$ATTACHED" || "$ATTACHED" == "None" ]]; then
    echo "  $POLICY_NAME not attached to $role — skipping"
    continue
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY-RUN] would detach $POLICY_NAME from $role"
  else
    aws iam detach-role-policy --role-name "$role" --policy-arn "$POLICY_ARN" >/dev/null
    echo "  Detached $POLICY_NAME from $role"
  fi
done
echo ""

# ── Step 2: Delete IAM policy ─────────────────────────────────────────────────
echo "==> [2/3] Delete IAM policy $POLICY_NAME..."

if ! aws iam get-policy --policy-arn "$POLICY_ARN" >/dev/null 2>&1; then
  echo "  Policy $POLICY_NAME not found — skipping"
else
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY-RUN] would delete all non-default versions and policy $POLICY_NAME"
  else
    # Delete all non-default versions first (required before DeletePolicy)
    NON_DEFAULT_VERSIONS=$(aws iam list-policy-versions --policy-arn "$POLICY_ARN" \
      --query "Versions[?!IsDefaultVersion].VersionId" \
      --output text 2>/dev/null || true)
    for vid in $NON_DEFAULT_VERSIONS; do
      [[ -z "$vid" || "$vid" == "None" ]] && continue
      aws iam delete-policy-version --policy-arn "$POLICY_ARN" --version-id "$vid" >/dev/null
      echo "  Deleted policy version $vid"
    done
    aws iam delete-policy --policy-arn "$POLICY_ARN" >/dev/null
    echo "  Deleted policy $POLICY_NAME"
  fi
fi
echo ""

# ── Step 3: Empty and delete S3 bucket ───────────────────────────────────────
echo "==> [3/3] Delete S3 bucket $BUCKET_NAME..."

if ! aws s3api head-bucket --bucket "$BUCKET_NAME" 2>/dev/null; then
  echo "  Bucket $BUCKET_NAME not found — skipping"
else
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY-RUN] would empty and delete bucket $BUCKET_NAME"
  else
    # Remove all versioned objects (handles versioning-enabled buckets)
    python3 - <<PY
import boto3, os
s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"))
bucket = "$BUCKET_NAME"
try:
    paginator = s3.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=bucket):
        objects = [
            {"Key": o["Key"], "VersionId": o["VersionId"]}
            for o in page.get("Versions", []) + page.get("DeleteMarkers", [])
        ]
        if objects:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": objects})
except Exception as e:
    print(f"  (version cleanup: {e})")
# Remove any remaining non-versioned objects
try:
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        objects = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if objects:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": objects})
except Exception as e:
    print(f"  (object cleanup: {e})")
PY
    aws s3api delete-bucket --bucket "$BUCKET_NAME" --region "$AWS_REGION" >/dev/null
    echo "  Deleted bucket $BUCKET_NAME"
  fi
fi
echo ""

echo ""
echo "Teardown complete for arbitium extension ($ENV_NAME)."
echo ""
