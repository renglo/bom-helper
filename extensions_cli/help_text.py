from __future__ import annotations

from typing import TypedDict


class HelpSection(TypedDict):
    name: str
    commands: list[str]


HELP_SECTIONS: list[HelpSection] = [
    {
        "name": "Any time",
        "commands": [
            "extensions help",
            "extensions status",
            "extensions show HANDLE",
            "extensions tree",
        ],
    },
    {
        "name": "Install (one-time incubation)",
        "commands": [
            "extensions install place HANDLE --hub --profile PROFILE",
            "extensions install place HANDLE --peer PEER --profile PROFILE",
            "extensions install place HANDLE --new-peer PEER --profile PROFILE [--compute fargate]",
            "extensions install plan",
            "extensions install config",
            "extensions install pin [--python-version X.Y.Z]",
            "extensions install publish [--skip-upload]",
            "extensions install deploy [--dry-run]",
            "extensions install test [--skip-synth]",
            "extensions install push [--yes]",
            "extensions install finish",
        ],
    },
]


COMMAND_BLURBS: dict[str, str] = {
    "help": "List nouns and install verbs.",
    "status": "Current incubation sheet and the next command.",
    "show": "Catalog owner, pin, and installer for one handle.",
    "tree": "Every catalog handle → hub or peer.",
    "place": "Start an incubation sheet (no files written except gitconvoy.toml).",
    "plan": "Print the config/pin/deploy/push plan without writing.",
    "config": "Edit deploy_targets.yml placement only.",
    "pin": "New BOM version file + pointer bump (not an in-place edit).",
    "publish": "Build the first wheel and upload it to CodeArtifact.",
    "deploy": "Synth/deploy the owning stack, then bootstrap write-state.",
    "test": "Installer + unique owner + optional CDK synth.",
    "push": "Commit and push *-bom main (this incubation only).",
    "finish": "Set role=product, refresh convoy membership, clear the sheet.",
}


def help_payload(topic: str = "") -> dict:
    topic = (topic or "").strip().lower()
    if topic in ("install", "install help"):
        section = next(s for s in HELP_SECTIONS if s["name"].startswith("Install"))
        return {
            "ok": True,
            "topic": "install",
            "commands": section["commands"],
            "blurbs": {k: COMMAND_BLURBS[k] for k in COMMAND_BLURBS if k != "help"},
        }
    if topic in COMMAND_BLURBS:
        return {"ok": True, "topic": topic, "blurb": COMMAND_BLURBS[topic]}
    return {
        "ok": True,
        "topic": "",
        "sections": HELP_SECTIONS,
        "blurbs": COMMAND_BLURBS,
    }


def format_help_text(topic: str = "") -> str:
    payload = help_payload(topic)
    if payload.get("blurb"):
        return f"{payload['topic']}: {payload['blurb']}"
    lines = ["extensions — tenant extension install and catalog inspect", ""]
    for section in payload.get("sections") or HELP_SECTIONS:
        if payload.get("topic") == "install" and not section["name"].startswith("Install"):
            continue
        lines.append(section["name"])
        for cmd in section["commands"]:
            blurb = ""
            for verb, text in COMMAND_BLURBS.items():
                token = f" {verb}"
                if cmd == f"extensions {verb}" or cmd.startswith(f"extensions {verb} "):
                    blurb = text
                    break
                if cmd.startswith(f"extensions install {verb}"):
                    blurb = text
                    break
            extra = f"  # {blurb}" if blurb else ""
            lines.append(f"  {cmd}{extra}")
        lines.append("")
    lines.append("Do not set customer-config extension_path. Do not deploy Stack A.")
    lines.append("After finish, pins and BOM pushes are git-convoy adopt — not this tool.")
    return "\n".join(lines).rstrip() + "\n"
