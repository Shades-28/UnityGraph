"""v1.6.0 -- deterministic query library."""

from __future__ import annotations

from pathlib import Path

import pytest

from unitygraph.build.builder import build_project
from unitygraph.mcp import queries

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject"


@pytest.fixture(scope="module")
def graph():
    return build_project(FIXTURE.resolve()).graph


def test_who_uses_returns_all_reference_kinds(graph):
    result = queries.who_uses(graph, "HealthSystem")
    assert result["found"] is True
    # HealthSystem is attached to Player, referenced by PlayerController
    # via GetComponent<HealthSystem>, and has no UnityEvent listeners.
    assert result["total_references"] > 0
    assert result["attached_to"], "HealthSystem should be attached somewhere"
    assert result["depended_on_by"], "PlayerController should depend on HealthSystem"
    for dep in result["depended_on_by"]:
        assert "sites" in dep
        assert dep["sites"], "v1.4+ should carry sites on depends_on"


def test_who_uses_unknown_script(graph):
    result = queries.who_uses(graph, "DoesNotExist")
    assert result["found"] is False


def test_impact_of_reaches_downstream(graph):
    # PlayerController depends on HealthSystem + Rigidbody. impact_of(PC)
    # should reach HealthSystem within 1 hop.
    result = queries.impact_of(graph, "PlayerController", hops=1)
    assert result["found"] is True
    impacted_names = {
        r["node"].get("name") for r in result["impacted"] if r["node"].get("type") == "Script"
    }
    assert "HealthSystem" in impacted_names


def test_find_singletons_reports_attachment_count(graph):
    result = queries.find_singletons(graph, min_attachments=1)
    # MiniUnity has UIButtonClick attached to UI_Button, HealthSystem on
    # Player + Enemy, PlayerController on Player. Every singleton entry
    # should have ≥1 attachment and carry sites where available.
    assert result["count"] >= 1
    for hit in result["singletons"]:
        assert hit["attachment_count"] >= 1
        assert hit["attachments"]


def test_inspector_overrides_for_detects_maxhealth(graph):
    # Enemy's HealthSystem has _maxHealth = 150, code default is 100.
    result = queries.inspector_overrides_for(graph, "HealthSystem")
    assert result["found"] is True
    all_overrides = [
        o for att in result["attachments"] for o in att["overrides"]
    ]
    max_health = next((o for o in all_overrides if o["field"] == "_maxHealth"), None)
    assert max_health is not None, "expected _maxHealth override to be detected"
    assert max_health["inspector_value"] == 150


def test_event_listeners_finds_onclick_to_playercontroller(graph):
    # UI_Button's m_OnClick → PlayerController.OnAttackPressed
    result = queries.event_listeners(graph, "PlayerController")
    assert result["found"] is True
    matched = [
        lst
        for lst in result["listeners"]
        if lst["method"] == "OnAttackPressed"
    ]
    assert matched, "should find m_OnClick listener on PlayerController.OnAttackPressed"
    # v1.5+ should carry a scene-file site for the listener.
    assert matched[0]["sites"]
    assert matched[0]["sites"][0]["kind"] == "subscribes_to"


def test_field_wiring_scopes_by_field_name(graph):
    # The UI_Button uses a missing/external script (common in stripped
    # fixtures) whose placeholder name comes from the guid prefix. Look
    # it up via the placeholder name.
    missing = queries.find_missing_scripts(graph)
    assert missing["count"] >= 1, "fixture should have at least one missing script"
    ui_script = missing["missing_scripts"][0]["script_id"].split("::")[1]
    result = queries.field_wiring(graph, ui_script, "m_OnClick")
    assert result["found"] is True
    assert result["wiring_count"] == 1
    wiring = result["wirings"][0]
    assert wiring["method"] == "OnAttackPressed"
    assert wiring["sites"]


def test_find_missing_scripts_reports_external_placeholders(graph):
    # The fixture's UI_Button references a script guid we can't resolve
    # (fe87c0e1...) -- it should surface as an external placeholder with
    # the GameObjects it's attached to.
    result = queries.find_missing_scripts(graph)
    assert result["count"] >= 1
    assert result["missing_scripts"][0]["attachment_count"] >= 1
    assert result["missing_scripts"][0]["guid"]


def test_impact_of_unknown_script(graph):
    result = queries.impact_of(graph, "NotAClass")
    assert result["found"] is False


def test_who_uses_inherited_by(graph):
    # DamagedEvent inherits UnityEvent<int> -- UnityEvent isn't a user
    # script so no inherits entry there. But the function must not fail.
    result = queries.who_uses(graph, "HealthSystem")
    assert "inherited_by" in result
    assert isinstance(result["inherited_by"], list)
