"""Reads Unity ``.meta`` sidecar files and builds a guid → source-path index.

Every asset in a Unity project has a ``.meta`` file next to it carrying a
persistent ``guid``. We use that index to resolve ``{fileID: 11500000, guid: X}``
script references back to a concrete ``.cs`` file.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path

import yaml

# Generated/library directories whose .meta files we must NOT index. Without
# this, ``Library/PackageCache/com.unity.ugui/.../Image.cs.meta`` leaks into
# the guid index and any scene reference to UnityEngine.UI.Image resolves to
# a path under ``Library/`` — misleading (the user can't edit that file) and
# floods query results with 100+ attachments of Unity built-ins.
#
# Note: ``Packages/`` is deliberately NOT in the skip list. Unity uses that
# directory for user-embedded packages (``Packages/com.mycompany.game/``)
# which contain real, editable user source. The cache of auto-downloaded
# package sources lives under ``Library/PackageCache/`` and is covered by
# skipping ``Library/``.
DEFAULT_SKIP_DIRS: frozenset[str] = frozenset(
    {"Library", "Temp", "obj", "Build", "Builds", "Logs"}
)

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


def build_guid_index(
    project_root: Path,
    *,
    skip_dirs: Iterable[str] | None = None,
) -> dict[str, Path]:
    """Walk ``project_root`` for ``.meta`` files and build a guid → asset-path map.

    The asset path returned is the file *without* the ``.meta`` suffix.
    We do NOT stat the asset path — on large projects the per-file syscall
    is a measurable hotspot, and a stale asset path is harmless: lookups
    against the index will return a path that doesn't resolve, which the
    caller already has to handle anyway.

    ``skip_dirs`` (defaults to ``DEFAULT_SKIP_DIRS``) drops any meta whose
    relative path contains one of these segments. Without this filter,
    ``Library/PackageCache/`` leaks Unity built-in scripts into the index,
    which then dominate any "used everywhere" or "missing script" query.
    Pass ``()`` to disable filtering (tests, raw dumps).
    """
    skip = frozenset(skip_dirs) if skip_dirs is not None else DEFAULT_SKIP_DIRS
    index: dict[str, Path] = {}
    for meta in project_root.rglob("*.meta"):
        if skip:
            try:
                rel_parts = set(meta.relative_to(project_root).parts)
            except ValueError:
                rel_parts = set()
            if rel_parts & skip:
                continue
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
