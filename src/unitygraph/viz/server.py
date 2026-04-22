"""Local HTTP + SSE server for the UnityGraph Observatory.

No FastAPI, no websockets — just stdlib ``http.server`` plus an SSE endpoint
that polls ``graph.json`` mtime and streams updates to connected browsers.

Endpoints:
    GET /                -> index.html
    GET /assets/*        -> static files from this package
    GET /graph.json      -> latest graph payload (transformed for react-force-graph)
    GET /events          -> SSE stream emitting "graph" events on file change

Why stdlib: zero runtime dependencies beyond what the package already has.
The server runs on localhost only; one user, one machine, no concurrency to
speak of.
"""

from __future__ import annotations

import json
import mimetypes
import queue
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from unitygraph.build.graph import Graph

ASSETS_DIR = Path(__file__).parent / "assets"


# ---------------------------------------------------------------------------
# Graph transformation — our graph.json shape -> react-force-graph-friendly
# ---------------------------------------------------------------------------


def transform_graph(graph_path: Path) -> dict[str, Any]:
    """Load ``graph.json`` and convert to the Observatory wire format.

    Observatory expects::

        {
          "schema_version": "1.1",
          "project_root": "...",
          "stats": {...},
          "nodes": [
            {
              "id": "...",
              "type": "Script|GameObject|Component|Scene|Prefab|...",
              "name": "...",
              "degree": N,
              "meta": { ... node-type-specific fields }
            }
          ],
          "links": [
            { "source": "...", "target": "...", "type": "attached_to|..." }
          ]
        }
    """
    if not graph_path.exists():
        return {"nodes": [], "links": [], "stats": {}, "project_root": "", "schema_version": ""}

    g = Graph.load(graph_path)
    degree: dict[str, int] = {}
    for edge in g.edges:
        degree[edge.from_id] = degree.get(edge.from_id, 0) + 1
        degree[edge.to_id] = degree.get(edge.to_id, 0) + 1

    nodes = []
    for n in g.nodes:
        name = str(n.data.get("name") or n.data.get("component_type") or n.id)
        meta: dict[str, Any] = {}
        # Pick a small, human-readable subset per node type.
        if n.type == "Script":
            meta = {
                "namespace": n.data.get("namespace"),
                "file_path": n.data.get("file_path"),
                "fields": n.data.get("fields") or [],
                "methods": [m.get("name") for m in n.data.get("methods") or []][:12],
                "script_type": n.data.get("script_type"),
                "execution_order": n.data.get("execution_order"),
            }
        elif n.type == "GameObject":
            meta = {
                "scope": n.data.get("scope"),
                "tag": n.data.get("tag"),
                "layer": n.data.get("layer"),
                "is_active": n.data.get("is_active"),
            }
        elif n.type == "Component":
            meta = {
                "component_type": n.data.get("component_type"),
                "scope": n.data.get("scope"),
                "inspector_values": n.data.get("inspector_values") or {},
            }
        elif n.type in ("Scene", "Prefab"):
            meta = {"file_path": n.data.get("file_path")}
        elif n.type == "AnimatorController":
            meta = {
                "parameters": n.data.get("parameters") or [],
                "layers": n.data.get("layers") or [],
            }
        elif n.type == "AnimState":
            meta = {"controller": n.data.get("controller")}
        elif n.type == "ShaderGraph":
            meta = {
                "properties": [p.get("name") for p in n.data.get("properties") or []][:12],
                "output_slots": n.data.get("output_slots") or [],
            }
        nodes.append(
            {
                "id": n.id,
                "type": n.type,
                "name": name,
                "degree": degree.get(n.id, 0),
                "meta": meta,
            }
        )

    links = []
    for e in g.edges:
        payload = {k: v for k, v in e.data.items() if k != "inspector_values"}
        # Edge-side inspector payloads are huge. Keep only a fingerprint.
        if "inspector_values" in e.data:
            iv = e.data["inspector_values"] or {}
            payload["override_count"] = sum(
                1 for v in iv.values() if isinstance(v, (int, float, str, bool))
            )
        link: dict[str, object] = {
            "source": e.from_id,
            "target": e.to_id,
            "type": e.type,
            "data": payload,
        }
        if e.sites:
            link["sites"] = [s.to_json() for s in e.sites]
        links.append(link)

    return {
        "schema_version": g.schema_version,
        "project_root": g.project_root,
        "stats": {
            "n_nodes": len(g.nodes),
            "n_edges": len(g.edges),
            "build_ms": g.build_ms,
        },
        "generated_at": g.generated_at,
        "nodes": nodes,
        "links": links,
    }


# ---------------------------------------------------------------------------
# SSE broadcaster — one background thread watches the file, wakes clients.
# ---------------------------------------------------------------------------


class GraphWatcher:
    """Polls graph.json mtime in the background; fan-outs to subscribers."""

    def __init__(self, graph_path: Path, poll_interval: float = 1.0) -> None:
        self.graph_path = graph_path
        self.poll_interval = poll_interval
        self._subscribers: list[queue.Queue[str]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._last_mtime_ns = 0

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def subscribe(self) -> queue.Queue[str]:
        q: queue.Queue[str] = queue.Queue(maxsize=32)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[str]) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                stat = self.graph_path.stat()
            except OSError:
                self._stop.wait(self.poll_interval)
                continue
            if stat.st_mtime_ns != self._last_mtime_ns:
                self._last_mtime_ns = stat.st_mtime_ns
                self._broadcast("graph")
            self._stop.wait(self.poll_interval)

    def _broadcast(self, event: str) -> None:
        with self._lock:
            dead: list[queue.Queue[str]] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    server_version = "UnityGraphObservatory/1.2"
    graph_path: Path
    watcher: GraphWatcher

    def log_message(self, format: str, *args: Any) -> None:  # silence stdlib noise
        return

    def _send(self, status: int, content: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._serve_file(ASSETS_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/assets/"):
            rel = path[len("/assets/") :]
            target = (ASSETS_DIR / rel).resolve()
            if not str(target).startswith(str(ASSETS_DIR.resolve())):
                self._send(403, b"forbidden", "text/plain")
                return
            if not target.exists() or not target.is_file():
                self._send(404, b"not found", "text/plain")
                return
            mime, _ = mimetypes.guess_type(str(target))
            self._serve_file(target, mime or "application/octet-stream")
            return
        if path == "/graph.json":
            payload = transform_graph(self.graph_path)
            self._send(
                200,
                json.dumps(payload).encode("utf-8"),
                "application/json; charset=utf-8",
            )
            return
        if path == "/events":
            self._serve_sse()
            return
        self._send(404, b"not found", "text/plain")

    def _serve_file(self, path: Path, content_type: str) -> None:
        try:
            data = path.read_bytes()
        except OSError:
            self._send(404, b"not found", "text/plain")
            return
        self._send(200, data, content_type)

    def _serve_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        q = self.watcher.subscribe()
        try:
            # Greet the client immediately so the browser flips to "connected".
            self.wfile.write(b"event: ready\ndata: {}\n\n")
            self.wfile.flush()
            # Also send an initial graph event so the UI renders on first paint.
            self.wfile.write(b"event: graph\ndata: {}\n\n")
            self.wfile.flush()

            while True:
                try:
                    event = q.get(timeout=15)
                except queue.Empty:
                    # Heartbeat so reverse proxies don't idle-close the stream.
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    continue
                try:
                    self.wfile.write(f"event: {event}\ndata: {{}}\n\n".encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return
        finally:
            self.watcher.unsubscribe(q)


def _find_free_port(preferred: int) -> int:
    """Return a usable localhost port, starting with ``preferred``."""
    for port in (preferred, *range(preferred + 1, preferred + 50)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return int(port)
    raise RuntimeError("no free port found in range")


def run_server(graph_path: Path, port: int = 7842) -> tuple[ThreadingHTTPServer, int]:
    """Spawn the HTTP + SSE server. Returns (server, bound_port).

    Caller is responsible for calling ``server.serve_forever()`` (blocking)
    or ``server.shutdown()`` to stop it cleanly.
    """
    port = _find_free_port(port)
    watcher = GraphWatcher(graph_path)

    handler = type(
        "BoundHandler",
        (_Handler,),
        {"graph_path": graph_path, "watcher": watcher},
    )
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    watcher.start()

    # When the server shuts down, stop the watcher thread too.
    original_shutdown = server.shutdown

    def _shutdown() -> None:
        watcher.stop()
        original_shutdown()

    server.shutdown = _shutdown  # type: ignore[method-assign]

    return server, port


def wait_until_ready(port: int, timeout: float = 5.0) -> bool:
    """Poll /graph.json until the server answers or the timeout elapses."""
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/graph.json", timeout=0.5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.05)
    return False


__all__ = [
    "GraphWatcher",
    "run_server",
    "transform_graph",
    "wait_until_ready",
]
