"""Tests for the v1.2 evidence layer: Site dataclass + Edge.sites + loader."""

from __future__ import annotations

import json
from pathlib import Path

from unitygraph.build.graph import Edge, Graph, Node, Site


def test_site_roundtrip_minimal():
    s = Site(file="Assets/Scripts/PC.cs", line=22, col=13, kind="get_component")
    payload = s.to_json()
    assert payload["file"] == "Assets/Scripts/PC.cs"
    assert payload["line"] == 22
    assert payload["col"] == 13
    assert payload["kind"] == "get_component"
    assert payload["confidence"] == "EXTRACTED"
    assert "snippet" not in payload  # empty fields omitted

    restored = Site.from_json(payload)
    assert restored == s


def test_site_roundtrip_full():
    s = Site(
        file="Assets/Scripts/PC.cs",
        line=22,
        col=13,
        end_line=22,
        end_col=52,
        kind="get_component",
        confidence="EXTRACTED",
        snippet="_rigidbody = GetComponent<Rigidbody>();",
        containing_method="Awake",
        reason="PlayerController caches a Rigidbody ref in Awake.",
    )
    restored = Site.from_json(s.to_json())
    assert restored == s


def test_edge_sites_append_dedups():
    e = Edge("a", "b", "depends_on")
    s1 = Site(file="x.cs", line=10, col=5, kind="method_call")
    s2 = Site(file="x.cs", line=10, col=5, kind="method_call")  # duplicate
    s3 = Site(file="x.cs", line=11, col=5, kind="method_call")  # distinct line
    e.add_site(s1)
    e.add_site(s2)
    e.add_site(s3)
    assert len(e.sites) == 2


def test_edge_to_json_omits_sites_when_empty():
    e = Edge("a", "b", "depends_on")
    assert "sites" not in e.to_json()

    e.add_site(Site(file="x.cs", line=10, col=5, kind="method_call"))
    assert "sites" in e.to_json()
    assert e.to_json()["sites"][0]["line"] == 10


def test_graph_load_v1_synthesizes_empty_sites(tmp_path: Path):
    """A v1.1 graph (no sites field on edges) must still load cleanly."""
    legacy = {
        "schema_version": "1.1",
        "generated_at": "2026-04-20T00:00:00+00:00",
        "project_root": "/tmp/legacy",
        "stats": {"n_nodes": 2, "n_edges": 1, "build_ms": 1},
        "nodes": [
            {"id": "script::X::X.cs", "type": "Script", "name": "X"},
            {"id": "script::Y::Y.cs", "type": "Script", "name": "Y"},
        ],
        "edges": [
            {
                "from": "script::X::X.cs",
                "to": "script::Y::Y.cs",
                "type": "depends_on",
                "via": "GetComponent",
                "target_type": "Y",
            }
        ],
    }
    path = tmp_path / "v1.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    g = Graph.load(path)
    assert len(g.edges) == 1
    assert g.edges[0].sites == []
    assert g.sites_available() is False


def test_graph_load_v2_restores_sites(tmp_path: Path):
    payload = {
        "schema_version": "1.2",
        "generated_at": "2026-04-23T00:00:00+00:00",
        "project_root": "/tmp/proj",
        "stats": {"n_nodes": 2, "n_edges": 1, "build_ms": 1},
        "nodes": [
            {"id": "script::X::X.cs", "type": "Script", "name": "X"},
            {"id": "script::Y::Y.cs", "type": "Script", "name": "Y"},
        ],
        "edges": [
            {
                "from": "script::X::X.cs",
                "to": "script::Y::Y.cs",
                "type": "depends_on",
                "sites": [
                    {
                        "file": "X.cs",
                        "line": 22,
                        "col": 13,
                        "kind": "get_component",
                        "confidence": "EXTRACTED",
                        "snippet": "_y = GetComponent<Y>();",
                        "containing_method": "Awake",
                    },
                ],
            }
        ],
    }
    path = tmp_path / "v2.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    g = Graph.load(path)
    assert g.sites_available() is True
    site = g.edges[0].sites[0]
    assert site.file == "X.cs"
    assert site.line == 22
    assert site.kind == "get_component"
    assert site.containing_method == "Awake"


def test_graph_roundtrip_preserves_sites(tmp_path: Path):
    g = Graph(project_root="/tmp/roundtrip")
    g.add_node(Node(id="a", type="Script", data={"name": "A"}))
    g.add_node(Node(id="b", type="Script", data={"name": "B"}))
    edge = Edge("a", "b", "depends_on")
    edge.add_site(
        Site(
            file="A.cs",
            line=5,
            col=1,
            kind="method_call",
            snippet="b.Method();",
            containing_method="Foo",
        )
    )
    g.add_edge(edge)

    path = tmp_path / "rt.json"
    g.write(path)
    restored = Graph.load(path)
    assert restored.sites_available()
    assert restored.edges[0].sites[0].snippet == "b.Method();"


def test_schema_version_is_1_2():
    """Sanity: constant matches the documented version."""
    from unitygraph.build.graph import SCHEMA_VERSION

    assert SCHEMA_VERSION == "1.2"
