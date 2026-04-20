"""Reads Unity ``.meta`` sidecar files and builds a guid → source-path index.

Every asset in a Unity project has a ``.meta`` file next to it carrying a
persistent ``guid``. We use that index to resolve ``{fileID: 11500000, guid: X}``
script references back to a concrete ``.cs`` file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import yaml


def load_meta_guid(meta_path: Path) -> str | None:
    try:
        payload = yaml.safe_load(meta_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(payload, dict):
        return None
    guid = payload.get("guid")
    return str(guid) if guid else None


def build_guid_index(project_root: Path) -> dict[str, Path]:
    """Walk ``project_root`` for ``.meta`` files and build a guid → asset-path map.

    The asset path returned is the file *without* the ``.meta`` suffix. Meta
    files reference assets that may or may not exist on disk — missing assets
    are skipped silently.
    """
    index: dict[str, Path] = {}
    for meta in project_root.rglob("*.meta"):
        asset = meta.with_suffix("")  # strips the .meta suffix
        # .cs.meta -> Foo.cs.meta.with_suffix('') = Foo.cs  (good)
        # Some meta files stem on folders; we accept either.
        if not asset.exists():
            # Folder metas have path `Foo/.meta` style; skip.
            continue
        guid = load_meta_guid(meta)
        if guid:
            index[guid] = asset
    return index


def resolve_script_path(guid: str, guid_index: Mapping[str, Path]) -> Path | None:
    """Resolve a MonoBehaviour script reference guid to its .cs file path."""
    path = guid_index.get(guid)
    if path is None:
        return None
    if path.suffix.lower() != ".cs":
        return None
    return path
