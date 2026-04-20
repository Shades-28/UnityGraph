"""Unit tests for the C# parser against the MiniUnityProject fixture."""

from __future__ import annotations

from pathlib import Path

import pytest

from unitygraph.build.parsers.cs_parser import parse_file

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject" / "Assets" / "Scripts"


@pytest.fixture(scope="module")
def player_controller():
    parsed = parse_file(FIXTURE / "PlayerController.cs")
    assert len(parsed.classes) == 1
    return parsed.classes[0]


@pytest.fixture(scope="module")
def health_system():
    parsed = parse_file(FIXTURE / "HealthSystem.cs")
    # HealthSystem.cs has 2 classes (DamagedEvent + HealthSystem).
    return parsed


@pytest.fixture(scope="module")
def enemy_ai():
    parsed = parse_file(FIXTURE / "EnemyAI.cs")
    assert len(parsed.classes) == 1
    return parsed.classes[0]


def test_player_controller_basic(player_controller):
    assert player_controller.name == "PlayerController"
    assert player_controller.namespace == "MiniUnity"
    assert player_controller.base_class == "MonoBehaviour"
    assert player_controller.is_monobehaviour is True


def test_player_controller_serialized_fields(player_controller):
    names = {f.name for f in player_controller.fields}
    assert {"_speed", "_jumpForce", "_maxHealth"}.issubset(names)
    speed = next(f for f in player_controller.fields if f.name == "_speed")
    assert speed.is_serialized is True
    assert speed.default_literal is not None
    assert "5" in speed.default_literal


def test_player_controller_lifecycle_methods(player_controller):
    methods = {m.name for m in player_controller.methods}
    assert "Awake" in methods
    assert "Start" in methods
    assert "Update" in methods
    lifecycle = {m.name for m in player_controller.methods if m.is_lifecycle}
    assert {"Awake", "Start", "Update"}.issubset(lifecycle)


def test_player_controller_get_component_calls(player_controller):
    # PlayerController.Awake() calls GetComponent<Rigidbody>() and GetComponent<HealthSystem>()
    assert "Rigidbody" in player_controller.get_component_types
    assert "HealthSystem" in player_controller.get_component_types


def test_health_system_has_multiple_classes(health_system):
    class_names = {c.name for c in health_system.classes}
    assert "HealthSystem" in class_names
    assert "DamagedEvent" in class_names


def test_enemy_ai(enemy_ai):
    assert enemy_ai.name == "EnemyAI"
    assert enemy_ai.is_monobehaviour is True
    assert "_detectionRange" in {f.name for f in enemy_ai.fields}
    assert "_damagePerHit" in {f.name for f in enemy_ai.fields}
