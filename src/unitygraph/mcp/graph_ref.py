"""Mutable reference to ``graph.json`` with auto-reload on file-mtime change.

Rationale: the MCP server is long-lived (one process per session). If the
user runs ``unitygraph build`` while the server is running, the file on
disk changes but the in-memory graph stays stale. Every tool call routes
through this reference, which re-stats the file and reloads on change.

Cost per call: one ``os.stat`` (microseconds). Reload cost: one
``Graph.load`` on graph.json (milliseconds for most projects, sub-second
even for a 72k-node graph).
"""

from __future__ import annotations

from pathlib import Path
from threading import RLock

from unitygraph.build.graph import Graph


class GraphRef:
    """Auto-reloading handle to a graph.json file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = RLock()
        self._graph: Graph | None = None
        self._mtime_ns: int = 0
        self._size: int = 0
        self.reload_count = 0
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    def current(self) -> Graph:
        """Return the current graph, reloading first if the file changed."""
        with self._lock:
            self._maybe_reload()
            assert self._graph is not None
            return self._graph

    def _maybe_reload(self) -> None:
        try:
            stat = self._path.stat()
        except OSError:
            return
        if stat.st_mtime_ns != self._mtime_ns or stat.st_size != self._size:
            self._load()

    def _load(self) -> None:
        try:
            self._graph = Graph.load(self._path)
            stat = self._path.stat()
            self._mtime_ns = stat.st_mtime_ns
            self._size = stat.st_size
            self.reload_count += 1
        except OSError:
            # If the file is temporarily missing (e.g. mid-rebuild), keep the
            # previous graph in memory. The next tool call will try again.
            return
