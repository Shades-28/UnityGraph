"""Reads Unity ``.meta`` sidecar files and builds a guid → source-path index.

Every asset in a Unity project has a ``.meta`` file next to it carrying a
persistent ``guid``. We use that index to resolve ``{fileID: 11500000, guid: X}``
script references back to a concrete ``.cs`` file.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

import yaml

# Meta files are simple: `guid: <32-hex-chars>` appears on a top-level line
# near the top. Full YAML parsing of every meta file in a large project
# (20k+ files) is a measurable hot path, so we try a cheap regex first and
# fall back to yaml.safe_load only if the file is unusual.
_GUID_RE = re.compile(r"^guid:\s*([a-fA-F0-9]{32})\s*$", re.MULTILINE)


def load_meta_guid(meta_path: Path) -> str | None:
    try:
        text = meta_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _GUID_RE.search(text)
    if m:
        return m.group(1)
    # Rare fallback: unusual whitespace or quoted guid.
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(payload, dict):
        return None
    guid = payload.get("guid")
    return str(guid) if guid else None


def build_guid_index(project_root: Path) -> dict[str, Path]:
    """Walk ``project_root`` for ``.meta`` files and build a guid → asset-path map.

    The asset path returned is the file *without* the ``.meta`` suffix.
    We do NOT stat the asset path — on large projects the per-file syscall
    is a measurable hotspot, and a stale asset path is harmless: lookups
    against the index will return a path that doesn't resolve, which the
    caller already has to handle anyway.
    """
    index: dict[str, Path] = {}
    for meta in project_root.rglob("*.meta"):
        guid = load_meta_guid(meta)
        if not guid:
            continue
        index[guid] = meta.with_suffix("")
    return index


def resolve_script_path(guid: str, guid_index: Mapping[str, Path]) -> Path | None:
    """Resolve a MonoBehaviour script reference guid to its .cs file path."""
    path = guid_index.get(guid)
    if path is None:
        return None
    if path.suffix.lower() != ".cs":
        return None
    return path
