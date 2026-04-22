"""v1.5.0 integration — scene-side edges carry sites with file-level lines."""

from __future__ import annotations

from pathlib import Path

import pytest

from unitygraph.build.builder import build_project

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject"


@pytest.fixture(scope="module")
def graph():
    return build_project(FIXTURE.resolve()).graph


def test_subscribes_to_edge_has_site(graph):
    subs = [e for e in graph.edges if e.type == "subscribes_to"]
    assert subs, "expected at least one subscribes_to edge"
    edge = subs[0]
    assert edge.sites, "subscribes_to edge should carry a site"
    site = edge.sites[0]
    assert site.kind == "subscribes_to"
    assert site.file.endswith("Main.unity")
    assert site.line > 0
    assert "->" in site.snippet  # "field -> method"


def test_attached_to_edges_have_header_line_sites(graph):
    attached = [e for e in graph.edges if e.type == "attached_to" and e.sites]
    assert attached, "at least one attached_to edge should have a site"
    for edge in attached:
        assert any(s.kind == "attached_to" for s in edge.sites)
        for s in edge.sites:
            if s.kind == "attached_to":
                assert s.line > 0
                assert s.file.endswith(".unity") or s.file.endswith(".prefab")


def test_on_click_site_points_at_correct_line(graph):
    """The UI_Button → PlayerController subscribes_to edge must point at
    m_OnClick in the scene file."""
    subs = [
        e
        for e in graph.edges
        if e.type == "subscribes_to" and "PlayerController" in e.to_id
    ]
    assert subs, "expected a subscribes_to edge targeting PlayerController"
    edge = subs[0]
    site = edge.sites[0]
    scene_text = (FIXTURE / "Assets" / "Scenes" / "Main.unity").read_text(encoding="utf-8")
    lines = scene_text.splitlines()
    assert "m_OnClick" in lines[site.line - 1]
