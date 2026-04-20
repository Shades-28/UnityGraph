"""In-process memoization for ``inject_context``.

Keyed by ``(task_hash, graph_id, strategy, n_hops, budget)``. The graph_id
combines the project root path with the graph file's mtime_ns, so a rebuilt
graph naturally invalidates the cache without extra bookkeeping.

Layer 3 (the behavior model) may later add a pattern_map_version to the key
so adaptive injection invalidates when the pattern map updates.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import InjectionResult


@dataclass(frozen=True)
class CacheKey:
    task_hash: str
    graph_id: str
    strategy: str
    n_hops: int
    budget: int


class InjectCache:
    def __init__(self, max_entries: int = 128) -> None:
        self._entries: OrderedDict[CacheKey, InjectionResult] = OrderedDict()
        self._max_entries = max_entries
        self._lock = RLock()
        self.hits = 0
        self.misses = 0

    def get(self, key: CacheKey) -> InjectionResult | None:
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                self.hits += 1
                return self._entries[key]
            self.misses += 1
            return None

    def put(self, key: CacheKey, result: InjectionResult) -> None:
        with self._lock:
            self._entries[key] = result
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.hits = 0
            self.misses = 0


def make_key(
    task_text: str,
    graph_id: str,
    strategy: str,
    n_hops: int,
    budget: int,
) -> CacheKey:
    task_hash = hashlib.sha256(task_text.strip().encode("utf-8")).hexdigest()[:16]
    return CacheKey(
        task_hash=task_hash,
        graph_id=graph_id,
        strategy=strategy or "auto",
        n_hops=n_hops,
        budget=budget,
    )


def graph_identity(graph_path: Path | None, project_root: str) -> str:
    """Return a stable identifier for a loaded graph.

    Prefers file mtime when we know where the graph came from; falls back to
    the project root when the graph is synthesized in-memory.
    """
    if graph_path is not None and graph_path.exists():
        stat = graph_path.stat()
        return f"{project_root}::{stat.st_mtime_ns}::{stat.st_size}"
    return project_root


# Module-level default cache used by the engine unless an explicit cache is
# passed. The MCP server owns a single process, so a shared cache is fine.
_DEFAULT_CACHE = InjectCache()


def default_cache() -> InjectCache:
    return _DEFAULT_CACHE
