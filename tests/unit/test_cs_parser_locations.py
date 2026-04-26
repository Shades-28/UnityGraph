"""Tests for v1.4.0 location-aware C# parsing -- CallSite + line numbers."""

from __future__ import annotations

from pathlib import Path

import pytest

from unitygraph.build.parsers.cs_parser import parse_file

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject" / "Assets" / "Scripts"


@pytest.fixture(scope="module")
def player_controller():
    return parse_file(FIXTURE / "PlayerController.cs")


def test_class_span_recorded(player_controller):
    pc = player_controller.classes[0]
    assert pc.class_line > 0
    assert pc.class_end_line > pc.class_line


def test_field_lines_recorded(player_controller):
    pc = player_controller.classes[0]
    by_name = {f.name: f for f in pc.fields}
    # _speed is the first SerializeField -- should be early in the file.
    assert by_name["_speed"].line >= 12  # depends on fixture layout
    assert by_name["_speed"].col > 0


def test_method_spans_recorded(player_controller):
    pc = player_controller.classes[0]
    methods = {m.name: m for m in pc.methods}
    awake = methods["Awake"]
    assert awake.line > 0
    assert awake.end_line > awake.line


def test_get_component_calls_have_locations(player_controller):
    pc = player_controller.classes[0]
    calls = pc.get_component_calls
    targets = {c.target for c in calls}
    assert "Rigidbody" in targets
    assert "HealthSystem" in targets

    rb_call = next(c for c in calls if c.target == "Rigidbody")
    assert rb_call.containing_method == "Awake"
    assert rb_call.containing_class == "PlayerController"
    assert rb_call.line > 0
    assert "GetComponent<Rigidbody>" in rb_call.snippet


def test_field_method_calls_resolve_receiver_to_field_type(player_controller):
    pc = player_controller.classes[0]
    # _rigidbody.AddForce(...) in Update should be captured; receiver
    # `_rigidbody` resolves to declared type Rigidbody.
    by_method = {(c.target, c.method): c for c in pc.field_method_calls}
    addforce = by_method.get(("Rigidbody", "AddForce"))
    assert addforce is not None, f"missing AddForce; got {list(by_method)}"
    assert addforce.containing_method == "Update"
    assert addforce.line > 0
    assert "_rigidbody.AddForce" in addforce.snippet.replace(" ", "")


def test_field_types_includes_private_fields(player_controller):
    """Non-serialized fields should still be in the type map so the
    builder can resolve method-call receivers."""
    types = player_controller.field_types
    assert types.get("_rigidbody") == "Rigidbody"
    assert types.get("_health") == "HealthSystem"


def test_health_system_addlistener_call_resolves(player_controller):
    """PlayerController.Start does _health.OnDamaged.AddListener(...).
    The current parser only resolves one level of member access, so it
    won't catch this nested call -- document this behavior explicitly."""
    pc = player_controller.classes[0]
    # Current behavior: _health.OnDamaged.AddListener is *not* one of
    # `field.Method()`. The receiver `_health.OnDamaged` is a
    # member_access_expression, not a bare identifier. So we expect
    # nothing here; v1.4 keeps the parser simple.
    targets = {(c.target, c.method) for c in pc.field_method_calls}
    assert ("HealthSystem", "AddListener") not in targets  # by design


def test_enemy_ai_get_component_call_in_update():
    parsed = parse_file(FIXTURE / "EnemyAI.cs")
    enemy = parsed.classes[0]
    calls = {c.target: c for c in enemy.get_component_calls}
    assert "HealthSystem" in calls
    assert calls["HealthSystem"].containing_method == "Update"
    assert calls["HealthSystem"].line > 0
