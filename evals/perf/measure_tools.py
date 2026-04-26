"""Measure per-tool response time against a pre-built graph.

Budget per plan §4.2: ``<500ms median`` for MCP tool responses on the
largest project. We measure the pure-Python tool layer here -- the MCP
transport adds negligible overhead on top.

Usage::

    python evals/perf/measure_tools.py path/to/graph.json
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

from unitygraph.build.graph import Graph
from unitygraph.mcp import tools

N_TRIALS = 10


def _first_gameobject_name(graph: Graph) -> str | None:
    for node in graph.nodes:
        if node.type == "GameObject":
            name = node.data.get("name")
            if isinstance(name, str) and name:
                return name
    return None


def _first_script_name(graph: Graph) -> str | None:
    for node in graph.nodes:
        if node.type == "Script":
            name = node.data.get("name")
            if isinstance(name, str) and name and not node.data.get("external"):
                return name
    return None


def _first_scene_name(graph: Graph) -> str | None:
    for node in graph.nodes:
        if node.type == "Scene":
            name = node.data.get("name")
            if isinstance(name, str) and name:
                return name
    return None


def _time_call(fn, *args) -> float:
    start = time.perf_counter()
    fn(*args)
    return (time.perf_counter() - start) * 1000.0


def measure(graph_path: Path) -> dict[str, dict[str, float]]:
    graph = Graph.load(graph_path)
    print(f"Graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    go_name = _first_gameobject_name(graph) or "Player"
    script_name = _first_script_name(graph) or "PlayerController"
    scene_name = _first_scene_name(graph) or "Main"
    print(f"Sample: gameobject={go_name!r} script={script_name!r} scene={scene_name!r}")

    calls: dict[str, tuple] = {
        "get_components": (tools.get_components, graph, go_name),
        "get_inspector_values": (
            tools.get_inspector_values,
            graph,
            script_name,
            go_name,
        ),
        "get_scene_graph": (tools.get_scene_graph, graph, scene_name),
        "find_script_usages": (tools.find_script_usages, graph, script_name),
        "get_event_connections": (tools.get_event_connections, graph, go_name),
    }

    results: dict[str, dict[str, float]] = {}
    for name, (fn, *args) in calls.items():
        samples = [_time_call(fn, *args) for _ in range(N_TRIALS)]
        results[name] = {
            "median_ms": statistics.median(samples),
            "p95_ms": sorted(samples)[int(len(samples) * 0.95) - 1]
            if len(samples) > 1
            else samples[0],
            "max_ms": max(samples),
        }
    return results


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python measure_tools.py <graph.json>", file=sys.stderr)
        return 2
    graph_path = Path(sys.argv[1])
    results = measure(graph_path)
    print()
    print(f"{'tool':25} {'median':>10} {'p95':>10} {'max':>10}")
    print("-" * 60)
    any_over_budget = False
    for name, stats in results.items():
        median = stats["median_ms"]
        p95 = stats["p95_ms"]
        max_ms = stats["max_ms"]
        flag = " ❌" if median > 500 else ""
        if median > 500:
            any_over_budget = True
        print(f"{name:25} {median:>9.2f}ms {p95:>9.2f}ms {max_ms:>9.2f}ms{flag}")

    if any_over_budget:
        print("\nOne or more tools exceed the 500ms median budget.")
        return 1
    print("\nAll tools under 500ms median budget.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
