#!/usr/bin/env bash
# Provision extension-specific AWS resources (standalone / legacy).
#
# For CDK installs, the same resources are synthesized as the {env}-extension stack
# from installer/infra/cdk_extension.json. Use this script only for manual/DevOps
# provisioning outside the CDK delivery path.
#
# This repo's resources (per platform env <env_name>):
#   - S3 bucket  {env}-threat-events-{account_id}
#   - IAM managed policy  {env}_actions_tt_policy
#
# Uses <env_name> only to attach that policy to platform roles created elsewhere:
#   {env}_tt_role, {env}-handlers-role, {env}-handlers-ecs-task
#
# Writes installer/infra/extra_resources.json (gitignored) for optional bootstrap merge.
# Does not read bootstrap state. Teardown uses naming conventions in teardown_extension.sh.
#
# Requires: aws CLI, bash, python3 (stdlib only, for extra_resources.json)
#
# Usage:
#   ./provision_extension.sh <env_name> [--aws-profile PROFILE] [--aws-region REGION] [--dry-run]

set -euo pipefail

export AWS_PAGER="${AWS_PAGER:-}"

INSTALLER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLICY_FILE="$INSTALLER_DIR/actions_tt_policy.json"
CONFIG_FILE="$INSTALLER_DIR/extension_config.json"
OUTPUT_FILE="$INSTALLER_DIR/extra_resources.json"

REGLO_DESCRIPTION="Reglo Deployment — extension actions policy"

ENV_NAME=""
AWS_PROFILE_ARG=""
AWS_REGION="us-east-1"
DRY_RUN=false

usage() {
  echo "Usage: $0 <env_name> [--aws-profile PROFILE] [--aws-region REGION] [--dry-run]" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --aws-profile)
      [[ $# -lt 2 ]] && usage
      AWS_PROFILE_ARG="$2"
      shift 2
      ;;
    --aws-region)
      [[ $# -lt 2 ]] && usage
      AWS_REGION="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    *)
      if [[ -z "$ENV_NAME" ]]; then
        ENV_NAME="$1"
        shift
      else
        echo "ERROR: unknown argument: $1" >&2
        usage
      fi
      ;;
  esac
done

[[ -z "$ENV_NAME" ]] && usage

POLICY_NAME="${ENV_NAME}_actions_tt_policy"
BUCKET_PREFIX="${ENV_NAME}-threat-events"

if [[ -n "$AWS_PROFILE_ARG" ]]; then
  export AWS_PROFILE="$AWS_PROFILE_ARG"
  export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"
fi
export AWS_REGION

if [[ ! -f "$POLICY_FILE" ]]; then
  echo "ERROR: policy document not found: $POLICY_FILE" >&2
  exit 1
fi

AWS_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
POLICY_ARN="arn:aws:iam::${AWS_ACCOUNT}:policy/${POLICY_NAME}"
BUCKET_NAME="${BUCKET_PREFIX}-${AWS_ACCOUNT}"
TT_POLICY_ARN="arn:aws:iam::${AWS_ACCOUNT}:policy/${ENV_NAME}_tt_policy"

echo "=========================================="
echo "Provision arbitium extension: $ENV_NAME"
echo "Region: $AWS_REGION   Account: $AWS_ACCOUNT"
[[ -n "${AWS_PROFILE:-}" ]] && echo "AWS Profile: $AWS_PROFILE"
[[ "$DRY_RUN" == "true" ]] && echo "Mode: DRY-RUN (no AWS changes will be made)"
echo "=========================================="
echo ""

# --- S3 ---
echo "=== S3 ==="
if aws s3api head-bucket --bucket "$BUCKET_NAME" 2>/dev/null; then
  echo "  S3 bucket already exists: $BUCKET_NAME"
else
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY-RUN] would create S3 bucket: $BUCKET_NAME (region: $AWS_REGION)"
  else
    if [[ "$AWS_REGION" == "us-east-1" ]]; then
      aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$AWS_REGION"
    else
      aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$AWS_REGION" \
        --create-bucket-configuration "LocationConstraint=$AWS_REGION"
    fi
    echo "  Created S3 bucket: $BUCKET_NAME"
  fi
fi
if [[ "$DRY_RUN" == "true" ]]; then
  echo "  [DRY-RUN] would tag S3 bucket with Description=Reglo Deployment"
else
  aws s3api put-bucket-tagging --bucket "$BUCKET_NAME" \
    --tagging "TagSet=[{Key=Description,Value=Reglo Deployment}]" \
    >/dev/null 2>&1 || true
fi
echo ""

# --- IAM policy ---
echo "=== IAM policy ==="
if aws iam get-policy --policy-arn "$POLICY_ARN" >/dev/null 2>&1; then
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY-RUN] would update policy $POLICY_NAME (create new default version)"
  else
    echo "  Updating policy $POLICY_NAME..."
    # IAM allows max 5 versions per policy; clean the oldest non-default before creating a new one.
    NON_DEFAULT_COUNT=$(aws iam list-policy-versions --policy-arn "$POLICY_ARN" \
      --query "length(Versions[?!IsDefaultVersion])" --output text 2>/dev/null || echo 0)
    if [[ "$NON_DEFAULT_COUNT" -ge 4 ]]; then
      OLDEST_VERSION=$(aws iam list-policy-versions --policy-arn "$POLICY_ARN" \
        --query "sort_by(Versions[?!IsDefaultVersion], &CreateDate)[0].VersionId" \
        --output text 2>/dev/null || true)
      if [[ -n "$OLDEST_VERSION" && "$OLDEST_VERSION" != "None" ]]; then
        aws iam delete-policy-version --policy-arn "$POLICY_ARN" --version-id "$OLDEST_VERSION" >/dev/null
      fi
    fi
    aws iam create-policy-version \
      --policy-arn "$POLICY_ARN" \
      --policy-document "file://${POLICY_FILE}" \
      --set-as-default >/dev/null
    echo "  Updated policy $POLICY_NAME"
  fi
else
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY-RUN] would create policy $POLICY_NAME from $POLICY_FILE"
  else
    echo "  Creating policy $POLICY_NAME..."
    aws iam create-policy \
      --policy-name "$POLICY_NAME" \
      --policy-document "file://${POLICY_FILE}" \
      --description "$REGLO_DESCRIPTION" >/dev/null
    echo "  Created policy $POLICY_NAME"
  fi
fi
echo ""

# --- Policy attachments ---
echo "=== Policy attachments ==="
ROLES_ATTACHED=()
TARGET_ROLES=(
  "${ENV_NAME}_tt_role"
  "${ENV_NAME}-handlers-role"
  "${ENV_NAME}-handlers-ecs-task"
)

attach_policy_to_role() {
  local role_name="$1"
  if ! aws iam get-role --role-name "$role_name" >/dev/null 2>&1; then
    echo "  WARNING: role '$role_name' not found — skipping attach" >&2
    return 1
  fi
  if aws iam list-attached-role-policies --role-name "$role_name" \
    --query "AttachedPolicies[?PolicyArn=='${POLICY_ARN}'].PolicyArn" \
    --output text | grep -q .; then
    echo "  ${POLICY_NAME} already attached to ${role_name}"
  else
    if [[ "$DRY_RUN" == "true" ]]; then
      echo "  [DRY-RUN] would attach ${POLICY_NAME} → ${role_name}"
    else
      aws iam attach-role-policy --role-name "$role_name" --policy-arn "$POLICY_ARN" >/dev/null
      echo "  Attached ${POLICY_NAME} → ${role_name}"
    fi
  fi
  return 0
}

for role in "${TARGET_ROLES[@]}"; do
  if attach_policy_to_role "$role"; then
    ROLES_ATTACHED+=("$role")
  fi
done
echo ""

# --- Blueprint upload permission check (read-only, runs in dry-run too) ---
echo "=== Blueprint upload permission check ==="
TT_ROLE="${ENV_NAME}_tt_role"
if aws iam get-role --role-name "$TT_ROLE" >/dev/null 2>&1; then
  if aws iam list-attached-role-policies --role-name "$TT_ROLE" \
    --query "AttachedPolicies[?PolicyArn=='${TT_POLICY_ARN}'].PolicyArn" \
    --output text | grep -q .; then
    echo "  OK: ${TT_ROLE} has ${ENV_NAME}_tt_policy → dynamodb:PutItem on ${ENV_NAME}_blueprints covered"
  else
    echo "  WARNING: ${TT_ROLE} is missing ${ENV_NAME}_tt_policy" >&2
    echo "           upload_blueprints.py may fail at runtime" >&2
  fi
else
  echo "  WARNING: role '$TT_ROLE' not found" >&2
fi
echo ""

# --- extra_resources.json (python3 stdlib only) ---
echo "=== Writing extra_resources.json ==="
if [[ "$DRY_RUN" == "true" ]]; then
  echo "  [DRY-RUN] would write extra_resources.json with:"
  echo "    ARBITIUM_THREAT_EVENTS_BUCKET=$BUCKET_NAME"
  [[ -f "$CONFIG_FILE" ]] && \
    python3 -c "
import json, sys
cfg = json.load(open('${CONFIG_FILE}'))
print('    EXTERNAL_HANDLERS=' + str(cfg.get('EXTERNAL_HANDLERS', '${ENV_NAME}')))
print('    EXTERNAL_HANDLERS_ECS_HANDLERS=' + str(cfg.get('EXTERNAL_HANDLERS_ECS_HANDLERS', '')))
for k, v in (cfg.get('SECRETS') or {}).items():
    print('    ' + k + '=' + ('[set]' if v else '[empty — would be omitted]'))
" 2>/dev/null || true
else
  ROLES_JSON="$(printf '%s\n' "${ROLES_ATTACHED[@]+"${ROLES_ATTACHED[@]}"}" | python3 -c "
import json, sys
roles = [r.strip() for r in sys.stdin if r.strip()]
print(json.dumps(roles))
")"

  export _PROVISION_ENV_NAME="$ENV_NAME"
  export _PROVISION_AWS_ACCOUNT="$AWS_ACCOUNT"
  export _PROVISION_AWS_REGION="$AWS_REGION"
  export _PROVISION_BUCKET_NAME="$BUCKET_NAME"
  export _PROVISION_POLICY_ARN="$POLICY_ARN"
  export _PROVISION_POLICY_NAME="$POLICY_NAME"
  export _PROVISION_ROLES_JSON="$ROLES_JSON"
  export _PROVISION_CONFIG_FILE="$CONFIG_FILE"
  export _PROVISION_OUTPUT_FILE="$OUTPUT_FILE"

  python3 <<'PY'
import json
import os
from datetime import datetime, timezone

env_name = os.environ["_PROVISION_ENV_NAME"]
aws_account = os.environ["_PROVISION_AWS_ACCOUNT"]
aws_region = os.environ["_PROVISION_AWS_REGION"]
bucket_name = os.environ["_PROVISION_BUCKET_NAME"]
policy_arn = os.environ["_PROVISION_POLICY_ARN"]
policy_name = os.environ["_PROVISION_POLICY_NAME"]
roles_attached = json.loads(os.environ["_PROVISION_ROLES_JSON"])
config_file = os.environ["_PROVISION_CONFIG_FILE"]
output_file = os.environ["_PROVISION_OUTPUT_FILE"]

config = {}
if os.path.isfile(config_file):
    with open(config_file, encoding="utf-8") as f:
        config = json.load(f)

external_handlers = str(config.get("EXTERNAL_HANDLERS") or env_name)
external_handlers_ecs = str(config.get("EXTERNAL_HANDLERS_ECS_HANDLERS") or "")

secrets_block = {}
for key, value in (config.get("SECRETS") or {}).items():
    if value:
        secrets_block[key] = value
    else:
        print(f"  NOTE: secret {key!r} is empty in extension_config.json — not written")

payload = {
    "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "env_name": env_name,
    "aws_account": aws_account,
    "aws_region": aws_region,
    "s3": {"threat_events_bucket": bucket_name},
    "iam": {
        "actions_policy_name": policy_name,
        "actions_policy_arn": policy_arn,
        "roles_attached": roles_attached,
    },
    "vars": {
        "ARBITIUM_THREAT_EVENTS_BUCKET": bucket_name,
        "EXTERNAL_HANDLERS": external_handlers,
        "EXTERNAL_HANDLERS_ECS_HANDLERS": external_handlers_ecs,
    },
    "secrets": secrets_block,
}

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2)
    f.write("\n")

print(f"\n  Written: {output_file}")
PY
fi

echo ""
echo "Done."
