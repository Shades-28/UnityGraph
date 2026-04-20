"""Unit tests for the scene/prefab parser against MiniUnityProject."""

from __future__ import annotations

from pathlib import Path

import pytest

from unitygraph.build.parsers.scene_parser import (
    SCRIPT_CLASS_ID,
    parse_file,
)

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject"
MAIN_SCENE = FIXTURE / "Assets" / "Scenes" / "Main.unity"
ENEMY_PREFAB = FIXTURE / "Assets" / "Prefabs" / "Enemy.prefab"


@pytest.fixture(scope="module")
def scene():
    return parse_file(MAIN_SCENE)


@pytest.fixture(scope="module")
def enemy_prefab():
    return parse_file(ENEMY_PREFAB)


def test_scene_gameobjects(scene):
    names = {go.name for go in scene.gameobjects}
    assert {"Main Camera", "Ground", "Player", "Enemy", "UI_Button"}.issubset(names)


def test_player_has_expected_components(scene):
    player = next(go for go in scene.gameobjects if go.name == "Player")
    comps = [scene.components_by_fileid[fid] for fid in player.component_file_ids]
    types = {c.type_name for c in comps}
    assert "Transform" in types
    assert "Rigidbody" in types
    assert "CapsuleCollider" in types
    # Two MonoBehaviour components (PlayerController + HealthSystem)
    mb_count = sum(1 for c in comps if c.class_id == SCRIPT_CLASS_ID)
    assert mb_count == 2


def test_player_controller_inspector_value(scene):
    player = next(go for go in scene.gameobjects if go.name == "Player")
    # Find the PlayerController MonoBehaviour via its guid.
    pc_guid = "11000000000000000000000000000001"
    comps = [scene.components_by_fileid[fid] for fid in player.component_file_ids]
    pc = next(c for c in comps if c.script_guid == pc_guid)
    # The Inspector override: _speed = 7.0 (code default is 5.0)
    assert pc.inspector_values.get("_speed") == 7.0
    assert pc.inspector_values.get("_jumpForce") == 8.0
    assert pc.inspector_values.get("_maxHealth") == 100


def test_ui_button_event_connection(scene):
    ui = next(go for go in scene.gameobjects if go.name == "UI_Button")
    comps = [scene.components_by_fileid[fid] for fid in ui.component_file_ids]
    button = next(c for c in comps if c.class_id == SCRIPT_CLASS_ID)
    assert button.event_connections, "expected at least one event connection"
    ec = button.event_connections[0]
    assert ec.method_name == "OnAttackPressed"
    # target should be the PlayerController MonoBehaviour fileID 300004
    assert ec.target_file_id == 300004


def test_enemy_prefab_gameobject(enemy_prefab):
    gos = enemy_prefab.gameobjects
    assert len(gos) == 1
    assert gos[0].name == "Enemy"


def test_enemy_prefab_has_enemy_ai_component(enemy_prefab):
    comps = enemy_prefab.components
    mb = [c for c in comps if c.class_id == SCRIPT_CLASS_ID]
    assert len(mb) == 1
    assert mb[0].script_guid == "11000000000000000000000000000003"
    assert mb[0].inspector_values.get("_detectionRange") == 10.0
    assert mb[0].inspector_values.get("_damagePerHit") == 10
