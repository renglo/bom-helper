from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from extensions_cli.errors import ExtensionsError

PHASES = (
    "placed",
    "configured",
    "pinned",
    "published",
    "deployed",
    "tested",
    "pushed",
)

NEXT_COMMAND = {
    "placed": "extensions install config",
    "configured": "extensions install pin",
    "pinned": "extensions install publish",
    "published": "extensions install deploy",
    "deployed": "extensions install test",
    "tested": "extensions install push",
    "pushed": "extensions install finish",
}

STATE_DIRNAME = ".extensions"
STATE_FILENAME = "state.json"


def state_path(workspace: Path) -> Path:
    return workspace / STATE_DIRNAME / STATE_FILENAME


def load(workspace: Path) -> dict[str, Any] | None:
    path = state_path(workspace)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def require(workspace: Path) -> dict[str, Any]:
    data = load(workspace)
    if data is None:
        raise ExtensionsError("nothing incubating. Run: extensions install place HANDLE …")
    return data


def save(workspace: Path, data: dict[str, Any]) -> Path:
    path = state_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def clear(workspace: Path) -> None:
    path = state_path(workspace)
    if path.is_file():
        path.unlink()


def set_phase(sheet: dict[str, Any], phase: str) -> dict[str, Any]:
    if phase not in PHASES:
        raise ExtensionsError(f"unknown phase: {phase}")
    sheet["phase"] = phase
    return sheet


def next_hint(sheet: dict[str, Any] | None) -> str:
    if not sheet:
        return "extensions install place HANDLE --hub|--peer PEER|--new-peer PEER"
    return NEXT_COMMAND.get(str(sheet.get("phase") or ""), "extensions status")
