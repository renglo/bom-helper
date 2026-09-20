"""Text edits to deploy_targets.yml that keep comments where possible."""

from __future__ import annotations

import re

from extensions_cli.errors import ExtensionsError


def ensure_package_slot(text: str, handle: str, python_dist: str, npm: str = "") -> str:
    pattern = rf"(?m)^  {re.escape(handle)}:\s*$"
    if re.search(pattern, text):
        return text
    block = f"  {handle}:\n    python: {python_dist}\n"
    if npm:
        block += f"    npm: {npm}\n"
    match = re.search(r"(?m)^packages:\s*(?:#.*)?$", text)
    if match is None:
        raise ExtensionsError("deploy_targets.yml has no packages: block")
    insert_at = _end_of_block(text, match.end())
    return text[:insert_at] + block + text[insert_at:]


def add_hub_python(text: str, dist: str) -> str:
    if _hub_has_dist(text, dist):
        return text
    match = re.search(r"(?m)^hub:\s*(?:#.*)?$\n(?:[ \t]+.*\n)*?[ \t]+python:\s*(?:#.*)?$", text)
    if match is None:
        raise ExtensionsError("deploy_targets.yml has no hub.python list")
    indent = "    "
    line = f"{indent}- {dist}\n"
    insert_at = _end_of_yaml_list(text, match.end())
    return text[:insert_at] + line + text[insert_at:]


def add_peer_extension(text: str, peer_id: str, handle: str) -> str:
    inline = re.search(
        rf"(?m)^([ \t]+){re.escape(peer_id)}:\n(?:[ \t]+.+\n)*?[ \t]+extensions:\s*\[([^\]]*)\]",
        text,
    )
    if inline:
        inner = inline.group(2).strip()
        parts = [p.strip() for p in inner.split(",") if p.strip()]
        if handle in parts:
            return text
        parts.append(handle)
        rebuilt = f"{inline.group(0).rsplit('[', 1)[0]}[{', '.join(parts)}]"
        return text[: inline.start()] + rebuilt + text[inline.end() :]
    return text


def add_peer_python(text: str, peer_id: str, dist: str) -> str:
    block = re.search(
        rf"(?m)^([ \t]+){re.escape(peer_id)}:\n(?:[ \t]+.+\n)*?[ \t]+python:\s*(?:#.*)?$",
        text,
    )
    if block is None:
        raise ExtensionsError(f"deploy_targets.yml: peers.{peer_id}.python not found")
    list_start = block.end()
    chunk = text[list_start : list_start + 800]
    if re.search(rf"^[ \t]+- {re.escape(dist)}\s*$", chunk, re.M):
        return text
    insert_at = list_start + _yaml_list_span(text[list_start:])
    return text[:insert_at] + f"      - {dist}\n" + text[insert_at:]


def add_new_peer(
    text: str,
    *,
    peer_id: str,
    handle: str,
    dist: str,
    compute: str,
    task_size: str,
    peers_bom: str,
) -> str:
    if re.search(rf"(?m)^[ \t]+{re.escape(peer_id)}:\s*$", text):
        return add_peer_extension(add_peer_python(text, peer_id, dist), peer_id, handle)
    block = (
        f"  {peer_id}:\n"
        f"    compute: {compute}\n"
        f"    task_size: {task_size}\n"
        f"    extensions: [{handle}]\n"
        f"    python:\n"
        f"      - {dist}\n"
        f"    peers_bom: {peers_bom}\n"
    )
    peers = re.search(r"(?m)^peers:\s*(?:#.*)?$", text)
    if peers is None:
        raise ExtensionsError("deploy_targets.yml has no peers: block")
    insert_at = _end_of_block(text, peers.end())
    return text[:insert_at] + block + text[insert_at:]


def set_version_pointer(text: str, key: str, version: str, *, peer_id: str = "") -> str:
    number = version.lstrip("v")
    if key == "bom":
        updated, n = re.subn(r"(?m)^bom:\s+\S+", f"bom: {number}", text, count=1)
        if n != 1:
            raise ExtensionsError("could not update bom: in deploy_targets.yml")
        return updated
    if key == "console_bom":
        if re.search(r"(?m)^console_bom:\s+\S+", text):
            updated, n = re.subn(
                r"(?m)^console_bom:\s+\S+", f"console_bom: {number}", text, count=1
            )
            if n != 1:
                raise ExtensionsError("could not update console_bom:")
            return updated
        return text
    if key == "peers_bom" and peer_id:
        pattern = rf"(?m)^(\s+{re.escape(peer_id)}:\n(?:\s+.+\n)*?\s+)peers_bom:\s+\S+"
        updated, n = re.subn(pattern, rf"\1peers_bom: {number}", text, count=1)
        if n != 1:
            raise ExtensionsError(f"could not update peers.{peer_id}.peers_bom")
        return updated
    raise ExtensionsError(f"unknown version pointer {key}")


def _hub_has_dist(text: str, dist: str) -> bool:
    match = re.search(r"(?m)^hub:\s*(?:#.*)?$", text)
    if match is None:
        return False
    end = _end_of_block(text, match.end())
    return bool(re.search(rf"^[ \t]+- {re.escape(dist)}\s*$", text[match.end() : end], re.M))


def _end_of_block(text: str, start: int) -> int:
    """Index just before the next top-level key (or EOF)."""
    pos = start
    if pos < len(text) and text[pos] == "\n":
        pos += 1
    idx = pos
    while idx < len(text):
        line_end = text.find("\n", idx)
        if line_end < 0:
            return len(text)
        line = text[idx:line_end]
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not line.startswith((" ", "\t")):
            return idx
        idx = line_end + 1
    return len(text)


def _end_of_yaml_list(text: str, after_python_key: int) -> int:
    return after_python_key + _yaml_list_span(text[after_python_key:])


def _yaml_list_span(chunk: str) -> int:
    if chunk.startswith("\n"):
        offset = 1
        body = chunk[1:]
    else:
        offset = 0
        body = chunk
    consumed = 0
    for line in body.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            consumed += len(line)
            continue
        if stripped.startswith("-"):
            consumed += len(line)
            continue
        break
    return offset + consumed
