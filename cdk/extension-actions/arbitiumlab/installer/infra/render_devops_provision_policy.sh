#!/usr/bin/env bash
# Render devops_extension_provision_policy.template.json for manual attach to a DevOps IAM user/group.
#
# This policy is NOT part of bootstrap. Attach it yourself (or hand the JSON to a sysadmin)
# before running provision_extension.sh or upload_blueprints.py.
#
# Usage:
#   ./render_devops_provision_policy.sh <env_name> [--account-id ID] [--aws-region REGION] [--aws-profile PROFILE] [-o FILE]
#
# <env_name> is the platform env (same as provision_extension.sh), not the extension repo folder name.
# Template placeholder __ENV_NAME__ is replaced with that env_name for resource ARNs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/devops_extension_provision_policy.template.json"

ENV_NAME=""
ACCOUNT_ID=""
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_PROFILE_ARG=""
OUTPUT=""

usage() {
  echo "Usage: $0 <env_name> [--account-id ID] [--aws-region REGION] [--aws-profile PROFILE] [-o FILE]" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --account-id)
      [[ $# -lt 2 ]] && usage
      ACCOUNT_ID="$2"
      shift 2
      ;;
    --aws-region)
      [[ $# -lt 2 ]] && usage
      AWS_REGION="$2"
      shift 2
      ;;
    --aws-profile)
      [[ $# -lt 2 ]] && usage
      AWS_PROFILE_ARG="$2"
      shift 2
      ;;
    -o|--output)
      [[ $# -lt 2 ]] && usage
      OUTPUT="$2"
      shift 2
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
[[ -f "$TEMPLATE" ]] || { echo "ERROR: template not found: $TEMPLATE" >&2; exit 1; }

if [[ -n "$AWS_PROFILE_ARG" ]]; then
  export AWS_PROFILE="$AWS_PROFILE_ARG"
  export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"
fi

if [[ -z "$ACCOUNT_ID" ]]; then
  ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)"
fi
[[ -z "$ACCOUNT_ID" || "$ACCOUNT_ID" == "None" ]] && {
  echo "ERROR: could not resolve account ID. Pass --account-id or configure AWS credentials." >&2
  exit 1
}

RENDERED="$(sed \
  -e "s/__ENV_NAME__/${ENV_NAME}/g" \
  -e "s/__EXTENSION__/${ENV_NAME}/g" \
  -e "s/__ACCOUNT_ID__/${ACCOUNT_ID}/g" \
  -e "s/__REGION__/${AWS_REGION}/g" \
  "$TEMPLATE")"

if [[ -n "$OUTPUT" ]]; then
  printf '%s\n' "$RENDERED" > "$OUTPUT"
  echo "Wrote $OUTPUT"
else
  printf '%s\n' "$RENDERED"
fi
