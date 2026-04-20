"""Unit tests for the MCP tool query layer against a built graph."""

from __future__ import annotations

from pathlib import Path

import pytest

from unitygraph.build.builder import build_project
from unitygraph.mcp import tools as gtools

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject"


@pytest.fixture(scope="module")
def graph():
    return build_project(FIXTURE).graph


def test_get_components_player(graph):
    out = gtools.get_components(graph, "Player")
    assert out["matches"], "expected Player to be found"
    match = out["matches"][0]
    assert match["component_count"] >= 5
    assert "PlayerController" in match["scripts"]
    assert "HealthSystem" in match["scripts"]
    assert "Rigidbody" in match["components"]
    assert "CapsuleCollider" in match["components"]


def test_get_components_case_insensitive(graph):
    out = gtools.get_components(graph, "player")
    assert out["matches"]


def test_get_inspector_values_player_controller_shows_speed_override(graph):
    out = gtools.get_inspector_values(graph, "PlayerController", "Player")
    assert out["found"] is True
    match = out["matches"][0]
    assert match["inspector_values"]["_speed"] == 7.0
    assert match["code_defaults"]["_speed"] == "5.0f"
    override_fields = {o["field"] for o in match["overrides"]}
    assert "_speed" in override_fields


def test_get_inspector_values_missing_gameobject(graph):
    out = gtools.get_inspector_values(graph, "PlayerController", "DoesNotExist")
    assert out["found"] is False


def test_get_scene_graph_main(graph):
    out = gtools.get_scene_graph(graph, "Main")
    assert out["found"] is True
    names = {go["name"] for go in out["gameobjects"]}
    assert {"Main Camera", "Ground", "Player", "Enemy", "UI_Button"}.issubset(names)
    assert out["count"] == 5


def test_find_script_usages_enemy_ai(graph):
    out = gtools.find_script_usages(graph, "EnemyAI")
    assert out["found"] is True
    # EnemyAI attached to one scene GO + one prefab GO
    assert out["count"] == 2
    go_scopes = {u["gameobject"]["scope"] for u in out["usages"]}
    # Scopes now include relative path suffix (to disambiguate duplicate stems)
    assert any(s.startswith("scene::Main::") for s in go_scopes)
    assert any(s.startswith("prefab::Enemy::") for s in go_scopes)


def test_find_script_usages_player_controller_inspector(graph):
    out = gtools.find_script_usages(graph, "PlayerController")
    assert out["count"] == 1
    assert out["usages"][0]["inspector_values"]["_speed"] == 7.0


def test_get_event_connections_player_has_incoming(graph):
    # UI_Button.onClick -> Player.PlayerController.OnAttackPressed
    # So Player should see an incoming event connection on PlayerController.
    out = gtools.get_event_connections(graph, "Player")
    assert out["found"] is True
    assert out["incoming"], f"expected incoming events on Player, got {out}"
    assert any(e.get("method") == "OnAttackPressed" for e in out["incoming"])


def test_get_event_connections_ui_button_has_outgoing(graph):
    out = gtools.get_event_connections(graph, "UI_Button")
    assert out["found"] is True
    assert out["outgoing"]
    assert any(e.get("method") == "OnAttackPressed" for e in out["outgoing"])
