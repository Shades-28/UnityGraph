"""I1 gate-4 test: Claude Code can derive the correct fix via MCP alone.

This is the single most important test in Iteration 1. It verifies that
against ``MiniUnityProject``, the graph + tools expose exactly the evidence
needed to move Claude Code from the wrong baseline answer to the correct
fix for the speed-proportional-slow bug.

If this fails, the I1 gate has not been met.
"""

from __future__ import annotations

from pathlib import Path

from unitygraph.build.builder import build_project
from unitygraph.mcp import tools

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject"


def test_headline_inspector_override_discoverable_via_mcp():
    graph = build_project(FIXTURE).graph

    # Step 1: Claude enumerates components on Player
    components = tools.get_components(graph, "Player")
    assert components["matches"], "Player GameObject must exist"
    scripts_on_player = set(components["matches"][0]["scripts"])
    assert "PlayerController" in scripts_on_player
    assert "HealthSystem" in scripts_on_player

    # Step 2: Claude reads PlayerController Inspector values
    inspector = tools.get_inspector_values(graph, "PlayerController", "Player")
    assert inspector["found"]
    match = inspector["matches"][0]

    # Gate assertion: Inspector override for _speed is visible
    assert match["inspector_values"]["_speed"] == 7.0
    assert match["code_defaults"]["_speed"] == "5.0f"
    override_fields = {o["field"] for o in match["overrides"]}
    assert "_speed" in override_fields, (
        "the `_speed` Inspector override MUST be flagged — this is the evidence "
        "Claude uses to avoid the baseline wrong-answer path."
    )


def test_headline_build_time_budget():
    # I1 success criterion §1.9: build under 60s on 50+ scripts. MiniUnityProject
    # has 3. We set a much tighter bound here to catch regressions early.
    result = build_project(FIXTURE)
    assert result.graph.build_ms < 5000, f"build_ms={result.graph.build_ms}ms exceeds 5s budget"
