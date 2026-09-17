#!/usr/bin/env bash
# Create bom-helper/venv and install CDK deps for peer stack synth/deploy.
#
# Usage (from ops/bom-helper):
#   bash setup-venv.sh
#   bash setup-venv.sh --python python3.12
#
# Then (from bom-helper/cdk):
#   cdk synth --app "../venv/bin/python app.py" --output "output/${PEER_ID}" ...
#   cdk deploy "${ENV}-peer-${PEER_ID}" --app "../venv/bin/python app.py" --output "output/${PEER_ID}" ...
#
# Idempotent: safe to re-run. Do not copy venv/ from another machine or OS.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
REQUIREMENTS="$SCRIPT_DIR/cdk/requirements.txt"
PYTHON="${PYTHON:-python3.12}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python) PYTHON="$2"; shift 2 ;;
    --python=*) PYTHON="${1#*=}"; shift ;;
    -h|--help)
      echo "Usage: bash setup-venv.sh [--python <exe>]"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

_venv_python() {
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    echo "$VENV_DIR/bin/python"
  elif [[ -x "$VENV_DIR/Scripts/python.exe" ]]; then
    echo "$VENV_DIR/Scripts/python.exe"
  fi
}

_is_cross_platform_venv() {
  local cfg="$VENV_DIR/pyvenv.cfg"
  [[ -d "$VENV_DIR/Scripts" ]] && return 0
  [[ -f "$cfg" ]] && grep -q '^home=.*\\' "$cfg" 2>/dev/null && return 0
  return 1
}

echo "bom-helper CDK venv"
echo "  python  : $PYTHON"
echo "  venv    : $VENV_DIR"

if [[ -d "$VENV_DIR" ]] && _is_cross_platform_venv; then
  echo "  ! venv was created on another OS — recreating"
  rm -rf "$VENV_DIR"
fi

if [[ ! -d "$VENV_DIR" ]]; then
  echo "  + creating venv"
  "$PYTHON" -m venv "$VENV_DIR"
fi

VENV_PYTHON="$(_venv_python)"
if [[ -z "$VENV_PYTHON" ]]; then
  echo "ERROR: venv python not found under $VENV_DIR" >&2
  echo "  Try: rm -rf venv && bash setup-venv.sh --python $PYTHON" >&2
  exit 1
fi

"$VENV_PYTHON" -m pip install --quiet --upgrade pip
"$VENV_PYTHON" -m pip install --quiet --upgrade -r "$REQUIREMENTS"

if ! "$VENV_PYTHON" -c "import aws_cdk" 2>/dev/null; then
  echo "ERROR: aws_cdk not importable after pip install" >&2
  exit 1
fi

echo "  OK      : $($VENV_PYTHON --version), aws_cdk importable"
echo
echo "Next:"
echo "  export ENV=<env_name> AWS_PROFILE=<profile> PEER_ID=<peer-id>"
echo "  bash scripts/deploy_peer_cdk.sh synth --peer-id \"\$PEER_ID\""
echo "  bash scripts/deploy_peer_cdk.sh deploy --peer-id \"\$PEER_ID\""
echo "  # Context from launcher/cdk/customer-config.json — see docs/PEERS.md"
