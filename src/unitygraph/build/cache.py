"""Per-file parse cache used by ``build --update``.

Keeps a sidecar JSON (``<output>/.parse_cache.json``) that maps
``relpath -> (mtime_ns, size, parser_version)``. On the next build, files
whose (mtime, size) match the cache entry are considered unchanged.

This is NOT a graph diff — the builder still emits a fresh graph every run.
The speedup comes from skipping expensive YAML/tree-sitter parses for files
that haven't changed. Use ``cache.load_parsed_result(path)`` / ``cache.save_parsed_result``
for per-file results; a miss just means the builder falls through to the real
parser.
"""

from __future__ import annotations

import json
import os
import pickle
from dataclasses import dataclass, field
from pathlib import Path

# Bump when any parser's output schema changes in an incompatible way.
# v3: v2.1.0 — guid index now filters Library/PackageCache; cached
# placeholder Script nodes from earlier builds must be rebuilt.
PARSER_VERSION = 3


@dataclass
class _CacheEntry:
    rel_path: str
    mtime_ns: int
    size: int
    parser_version: int
    blob_path: str  # relative to cache_dir


@dataclass
class ParseCache:
    cache_dir: Path
    entries: dict[str, _CacheEntry] = field(default_factory=dict)

    @classmethod
    def load(cls, cache_dir: Path) -> ParseCache:
        manifest = cache_dir / "manifest.json"
        if not manifest.exists():
            return cls(cache_dir=cache_dir)
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(cache_dir=cache_dir)
        cache = cls(cache_dir=cache_dir)
        for rel, data in payload.get("entries", {}).items():
            if data.get("parser_version") != PARSER_VERSION:
                continue
            cache.entries[rel] = _CacheEntry(
                rel_path=rel,
                mtime_ns=int(data["mtime_ns"]),
                size=int(data["size"]),
                parser_version=int(data["parser_version"]),
                blob_path=str(data["blob_path"]),
            )
        return cache

    def write(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "parser_version": PARSER_VERSION,
            "entries": {
                rel: {
                    "mtime_ns": e.mtime_ns,
                    "size": e.size,
                    "parser_version": e.parser_version,
                    "blob_path": e.blob_path,
                }
                for rel, e in self.entries.items()
            },
        }
        (self.cache_dir / "manifest.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def get(self, rel_path: str, absolute_path: Path) -> object | None:
        entry = self.entries.get(rel_path)
        if entry is None:
            return None
        try:
            stat = absolute_path.stat()
        except OSError:
            return None
        if stat.st_mtime_ns != entry.mtime_ns or stat.st_size != entry.size:
            return None
        blob = self.cache_dir / entry.blob_path
        try:
            with blob.open("rb") as f:
                loaded: object = pickle.load(f)
        except (OSError, pickle.UnpicklingError, EOFError, AttributeError):
            return None
        return loaded

    def put(self, rel_path: str, absolute_path: Path, payload: object) -> None:
        try:
            stat = absolute_path.stat()
        except OSError:
            return
        blob_rel = _blob_path_for(rel_path)
        blob_abs = self.cache_dir / blob_rel
        blob_abs.parent.mkdir(parents=True, exist_ok=True)
        try:
            with blob_abs.open("wb") as f:
                pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        except OSError:
            return
        self.entries[rel_path] = _CacheEntry(
            rel_path=rel_path,
            mtime_ns=stat.st_mtime_ns,
            size=stat.st_size,
            parser_version=PARSER_VERSION,
            blob_path=blob_rel,
        )


def _blob_path_for(rel_path: str) -> str:
    # Map any OS-safe file path into a predictable slot; no hashing, since
    # callers already pass relative Unity-rooted paths.
    safe = rel_path.replace("\\", "/").replace(":", "_")
    return os.path.join("blobs", safe + ".pkl")
