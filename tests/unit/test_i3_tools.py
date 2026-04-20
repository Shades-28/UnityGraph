"""Unit tests for the new I3 MCP tools against a real external project.

These tests only run when the external Unity corpus is available (`D:/PR/Unity`);
otherwise they skip. The clash.io fixture is small enough for fast test runs
and contains the feature variety needed (AnimatorControllers, prefab variants,
ShaderGraphs).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from unitygraph.build.builder import build_project
from unitygraph.mcp import tools as gtools

EXTERNAL_ROOT = Path(os.environ.get("UNITYGRAPH_EXTERNAL_ROOT", "D:/PR/Unity"))
CLASH = EXTERNAL_ROOT / "clash.io"


@pytest.fixture(scope="module")
def clash_graph():
    if not CLASH.exists():
        pytest.skip(f"clash.io fixture not available at {CLASH}")
    return build_project(CLASH).graph


def test_graph_has_new_node_types(clash_graph):
    by_type = {}
    for n in clash_graph.nodes:
        by_type[n.type] = by_type.get(n.type, 0) + 1
    # clash.io has 17 .controller files and 5 .shadergraph files (pre-audited).
    assert by_type.get("AnimatorController", 0) >= 10
    assert by_type.get("AnimState", 0) >= 50
    assert by_type.get("ShaderGraph", 0) >= 1


def test_graph_has_variant_edges(clash_graph):
    variant_edges = [e for e in clash_graph.edges if e.type == "is_variant_of"]
    assert variant_edges, "expected at least one is_variant_of edge in clash.io"


def test_get_prefab_chain_returns_chain(clash_graph):
    # Find any prefab with a variant chain.
    variant_edges = [e for e in clash_graph.edges if e.type == "is_variant_of"]
    assert variant_edges
    variant_node = next(n for n in clash_graph.nodes if n.id == variant_edges[0].from_id)
    out = gtools.get_prefab_chain(clash_graph, str(variant_node.data["name"]))
    assert out["found"] is True
    assert out["chains"], out
    # Depth must be > 1 to prove the walk worked.
    assert any(c["depth"] >= 2 for c in out["chains"])


def test_get_neighbors_1_hop(clash_graph):
    # Pick a GameObject with at least one component.
    go = next(
        n
        for n in clash_graph.nodes
        if n.type == "GameObject"
        and any(e for e in clash_graph.edges if e.type == "attached_to" and e.to_id == n.id)
    )
    out = gtools.get_neighbors(clash_graph, go.id, hops=1)
    assert out["found"] is True
    assert out["neighbor_count"] >= 1
    for neighbor in out["neighbors"]:
        assert neighbor["_hop"] == 1


def test_shortest_path_within_same_gameobject(clash_graph):
    # Two components on the same GameObject should have a path of length 2
    # (via attached_to → GameObject → attached_to).
    for go in clash_graph.nodes:
        if go.type != "GameObject":
            continue
        attached = [e for e in clash_graph.edges if e.type == "attached_to" and e.to_id == go.id]
        if len(attached) < 2:
            continue
        a, b = attached[0].from_id, attached[1].from_id
        out = gtools.shortest_path(clash_graph, a, b)
        assert out["found"] is True
        assert out["hops"] <= 2
        return
    pytest.skip("no GameObject with 2+ components in clash.io (unexpected)")


def test_query_graph_matches_known_script_name(clash_graph):
    # Pick the name of any actual Script node and feed it into a prose query.
    script = next(n for n in clash_graph.nodes if n.type == "Script" and not n.data.get("external"))
    query = f"How does {script.data['name']} work?"
    out = gtools.query_graph(clash_graph, query, max_nodes=30)
    assert out["seed_matches"], out
    assert script.id in out["seed_matches"]
