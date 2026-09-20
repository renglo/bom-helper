#!/usr/bin/env bash
# Create bom-helper/bom-venv: CDK deps + extensions CLI on PATH (like git-convoy).
#
# Named bom-venv (not venv) so it is distinguishable from the application venv
# and obvious which environment a terminal has activated.
#
# Usage (from ops/bom-helper):
#   bash setup-venv.sh
#   bash setup-venv.sh --python python3.12
#   source bom-venv/bin/activate
#   extensions help
#
# Idempotent: safe to re-run. Do not copy bom-venv/ from another machine or OS.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_NAME="${BOM_VENV_NAME:-bom-venv}"
REQUIREMENTS="$SCRIPT_DIR/cdk/requirements.txt"
PYTHON="${PYTHON:-python3.12}"
PYPI_INDEX="https://pypi.org/simple"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python) PYTHON="$2"; shift 2 ;;
    --python=*) PYTHON="${1#*=}"; shift ;;
    --venv) VENV_NAME="$2"; shift 2 ;;
    --venv=*) VENV_NAME="${1#*=}"; shift ;;
    -h|--help)
      echo "Usage: bash setup-venv.sh [--python <exe>] [--venv <dirname>]"
      echo "  --venv defaults to bom-venv (override with BOM_VENV_NAME)"
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

VENV_DIR="$SCRIPT_DIR/$VENV_NAME"

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

echo "bom-helper venv (CDK + extensions CLI)"
echo "  python  : $PYTHON"
echo "  venv    : $VENV_DIR"

if [[ -d "$VENV_DIR" ]] && _is_cross_platform_venv; then
  echo "  ! venv was created on another OS — recreating"
  rm -rf "$VENV_DIR"
fi

if [[ "$VENV_NAME" != "venv" && -d "$SCRIPT_DIR/venv" ]]; then
  echo "  ! legacy $SCRIPT_DIR/venv still exists — safe to delete: rm -rf ops/bom-helper/venv"
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
"$VENV_PYTHON" -m pip install --quiet --isolated --index-url "$PYPI_INDEX" -e ".[dev]"

if ! "$VENV_PYTHON" -c "import aws_cdk" 2>/dev/null; then
  echo "ERROR: aws_cdk not importable after pip install" >&2
  exit 1
fi

if ! "$VENV_PYTHON" -c "import extensions_cli" 2>/dev/null; then
  echo "ERROR: extensions_cli not importable after pip install -e" >&2
  exit 1
fi

echo "  OK      : $($VENV_PYTHON --version), aws_cdk + extensions CLI"
echo
echo "Activate (then run from any folder in the monorepo):"
echo "  source $VENV_NAME/bin/activate"
echo "  extensions help"
echo "  extensions tree"
echo
echo "Peer CDK (unchanged):"
echo "  export ENV=<env_name> PEER_ID=<peer-id>"
echo "  bash scripts/deploy_peer_cdk.sh deploy --peer-id \"\$PEER_ID\" --profile <profile>"
echo
echo "Docs: docs/EXTENSIONS.md"
