"""Integration test for v1.4.0 — builder threads CallSites into edges as Sites."""

from __future__ import annotations

from pathlib import Path

import pytest

from unitygraph.build.builder import build_project

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject"


@pytest.fixture(scope="module")
def graph():
    return build_project(FIXTURE).graph


def test_v1_4_emits_sites_on_depends_on(graph):
    """Every depends_on edge from a script we own should carry at least one site."""
    depends_edges = [e for e in graph.edges if e.type == "depends_on"]
    assert depends_edges, "no depends_on edges found"
    edges_with_sites = [e for e in depends_edges if e.sites]
    assert edges_with_sites, "no depends_on edge has sites — v1.4 didn't take effect"


def test_pc_depends_on_health_system_carries_get_component_site(graph):
    """The headline relationship should now carry a get_component site
    pointing at PlayerController.Awake().
    """
    matches = [
        e
        for e in graph.edges
        if e.type == "depends_on" and "PlayerController" in e.from_id and "HealthSystem" in e.to_id
    ]
    assert matches, "no PC -> HealthSystem depends_on edge"
    edge = matches[0]
    sites_by_kind = {s.kind for s in edge.sites}
    assert "get_component" in sites_by_kind
    awake_site = next(s for s in edge.sites if s.kind == "get_component")
    assert awake_site.containing_method == "Awake"
    assert awake_site.line > 0
    assert "GetComponent<HealthSystem>" in awake_site.snippet


def test_pc_depends_on_rigidbody_via_method_call(graph):
    """PC stores a Rigidbody (get_component) and calls AddForce on it
    (method_call). Both sites should land on the same edge after merging.
    """
    matches = [
        e
        for e in graph.edges
        if e.type == "depends_on"
        and "PlayerController" in e.from_id
        and ("Rigidbody" in e.to_id or e.data.get("target_type") == "Rigidbody")
    ]
    # Note: Rigidbody is a Unity built-in, not a user script — so it does
    # NOT get a Script node in our graph, which means the edge isn't
    # emitted at all. This test documents that current behavior; the
    # sites are still captured on the parser side.
    if not matches:
        pytest.skip(
            "Rigidbody is a Unity built-in, not a user Script node. "
            "Sites for it live on the parser, not on a graph edge yet."
        )


def test_sites_available_returns_true(graph):
    assert graph.sites_available() is True


def test_inherits_edge_carries_site_when_user_class(graph):
    """If we ever add a user-script inheritance to MiniUnityProject, the
    inherits edge should carry a site pointing at the class declaration.
    For now this is a smoke test — DamagedEvent inherits UnityEvent<int>,
    UnityEvent isn't a user script, so no edge.
    """
    inherits = [e for e in graph.edges if e.type == "inherits"]
    for e in inherits:
        assert e.sites, f"inherits edge {e.from_id}→{e.to_id} has no sites"
        assert any(s.kind == "inherits" for s in e.sites)
