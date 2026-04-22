"""Tests for the Observatory server backend (graph transform + HTTP + SSE)."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from unitygraph.build.builder import build_project
from unitygraph.viz.server import GraphWatcher, run_server, transform_graph

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject"


@pytest.fixture
def mini_graph(tmp_path):
    """Build MiniUnityProject into a tmp dir we can mutate freely."""
    out_dir = tmp_path / "graph-out"
    result = build_project(FIXTURE)
    graph_path = out_dir / "graph.json"
    result.graph.write(graph_path)
    return graph_path


def test_transform_graph_handles_missing_file(tmp_path):
    out = transform_graph(tmp_path / "nope.json")
    assert out["nodes"] == []
    assert out["links"] == []


def test_transform_graph_returns_expected_shape(mini_graph):
    payload = transform_graph(mini_graph)
    assert payload["schema_version"]
    assert payload["stats"]["n_nodes"] > 0
    assert payload["stats"]["n_edges"] > 0
    # Nodes carry {id, type, name, degree, meta}
    sample = payload["nodes"][0]
    for key in ("id", "type", "name", "degree", "meta"):
        assert key in sample
    # Links carry {source, target, type, data}
    if payload["links"]:
        link = payload["links"][0]
        for key in ("source", "target", "type", "data"):
            assert key in link


def test_transform_graph_surfaces_edge_sites_for_observatory(mini_graph):
    """v2.0: links in the viz payload must carry sites[] so the Observatory
    evidence popover can render file:line click-throughs."""
    payload = transform_graph(mini_graph)
    links_with_sites = [lk for lk in payload["links"] if lk.get("sites")]
    assert links_with_sites, "v2.0 viz payload must include sites[] on at least one link"
    site = links_with_sites[0]["sites"][0]
    for key in ("file", "line", "kind"):
        assert key in site


def test_transform_graph_player_controller_shows_fields(mini_graph):
    payload = transform_graph(mini_graph)
    pc = next(
        n for n in payload["nodes"] if n["type"] == "Script" and n["name"] == "PlayerController"
    )
    assert pc["meta"]["script_type"] == "MonoBehaviour"
    field_names = {f["name"] for f in pc["meta"]["fields"]}
    assert "_speed" in field_names
    assert pc["degree"] > 0


def test_watcher_notifies_subscribers_on_mtime_change(mini_graph):
    watcher = GraphWatcher(mini_graph, poll_interval=0.05)
    q = watcher.subscribe()
    watcher.start()
    try:
        # Drain the initial "file exists" event. The watcher always emits one
        # on the first successful stat so new subscribers get current state.
        first = q.get(timeout=1.0)
        assert first == "graph"

        # Pause, then touch the file — expect a second event.
        time.sleep(0.15)
        mini_graph.write_text(mini_graph.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        event = q.get(timeout=1.0)
        assert event == "graph"
    finally:
        watcher.stop()


def test_http_graph_endpoint_serves_payload(mini_graph):
    server, port = run_server(mini_graph, port=17842)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/graph.json", timeout=2) as resp:
            assert resp.status == 200
            payload = json.loads(resp.read())
        assert payload["stats"]["n_nodes"] > 0
        assert any(n["type"] == "Script" for n in payload["nodes"])
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_http_index_serves_html(mini_graph):
    server, port = run_server(mini_graph, port=17843)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8", errors="replace")
        assert "UnityGraph Observatory" in body
        assert "/assets/observatory.css" in body
        assert "/assets/observatory.js" in body
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_http_assets_are_served(mini_graph):
    server, port = run_server(mini_graph, port=17844)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/assets/observatory.css", timeout=2
        ) as resp:
            assert resp.status == 200
            css = resp.read().decode("utf-8", errors="replace")
        assert "Observatory" in css or ":root" in css
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/assets/observatory.js", timeout=2
        ) as resp:
            assert resp.status == 200
            js = resp.read().decode("utf-8", errors="replace")
        assert "ForceGraph" in js
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_sse_endpoint_sends_graph_event_on_file_change(mini_graph):
    """End-to-end live-reactivity proof: spawn server, open SSE, touch the
    graph file, assert a `graph` event arrives on the stream."""
    server, port = run_server(mini_graph, port=17845)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/events",
            headers={"Accept": "text/event-stream"},
        )
        resp = urllib.request.urlopen(req, timeout=4)

        def read_until(marker: str, deadline: float) -> str:
            buf = b""
            while time.monotonic() < deadline:
                chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(4096)
                if not chunk:
                    continue
                buf += chunk
                if marker in buf.decode("utf-8", errors="replace"):
                    return buf.decode("utf-8", errors="replace")
            raise AssertionError(f"marker {marker!r} not seen in SSE stream")

        # The server sends `ready` + initial `graph` immediately.
        read_until("event: graph", time.monotonic() + 3.0)

        # Now touch the file and expect a NEW `graph` event.
        time.sleep(0.2)
        mini_graph.write_text(mini_graph.read_text(encoding="utf-8"), encoding="utf-8")

        # Wait for a second graph event on the stream.
        read_until("event: graph", time.monotonic() + 3.0)
        resp.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)
