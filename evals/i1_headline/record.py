"""Headline test — simulates a Claude Code session against the MiniUnityProject graph.

Runs the exact MCP tool sequence that Claude Code is expected to run for the
speed-proportional-slow bug, asserts the returned data is sufficient to derive
the correct fix, and writes ``transcript.json`` as the gate-4 evidence for I1.

The transcript is intended to be diffable across runs — a regression here
means the graph or the tools have changed in a way that would break real
Claude Code sessions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from unitygraph.build.builder import build_project
from unitygraph.mcp import tools

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject"
OUT = Path(__file__).parent / "transcript.json"

TASK_TEXT = "Make the slow effect proportional to actual player speed."


def main() -> int:
    print(f"[record] Building graph for {FIXTURE}...")
    result = build_project(FIXTURE)
    graph = result.graph
    print(
        f"[record] nodes={len(graph.nodes)} edges={len(graph.edges)} "
        f"time={graph.build_ms}ms warnings={len(result.report.warnings)}"
    )

    session: list[dict] = []

    def step(call: str, args: dict, response: dict) -> None:
        session.append({"call": call, "args": args, "response": response})
        print(f"[record] -> {call}({args}) ... keys={list(response)[:8]}")

    step(
        "get_components",
        {"gameobject_name": "Player"},
        tools.get_components(graph, "Player"),
    )
    step(
        "get_inspector_values",
        {"component_name": "PlayerController", "gameobject_name": "Player"},
        tools.get_inspector_values(graph, "PlayerController", "Player"),
    )

    inspector_resp = session[1]["response"]
    overrides = inspector_resp["matches"][0]["overrides"]
    inspector_values = inspector_resp["matches"][0]["inspector_values"]

    # The key assertion: graph exposes the Inspector override Claude needs.
    assert inspector_values["_speed"] == 7.0, inspector_values
    assert any(o["field"] == "_speed" for o in overrides), overrides

    proposed_diff = (
        "diff --git a/Assets/Scripts/PlayerController.cs b/Assets/Scripts/PlayerController.cs\n"
        "--- a/Assets/Scripts/PlayerController.cs\n"
        "+++ b/Assets/Scripts/PlayerController.cs\n"
        "@@\n"
        "     private void HandleDamaged(int amount)\n"
        "     {\n"
        "-        _speedMultiplier = Mathf.Max(0.1f, 1.0f - (amount / 5.0f));\n"
        "+        _speedMultiplier = Mathf.Max(0.1f, 1.0f - (amount / _speed));\n"
        "     }\n"
    )

    transcript = {
        "task": TASK_TEXT,
        "fixture": str(FIXTURE.resolve()),
        "mcp_calls": session,
        "inspector_override_detected": {
            "field": "_speed",
            "inspector_value": inspector_values["_speed"],
            "code_default": inspector_resp["matches"][0]["code_defaults"].get("_speed"),
        },
        "proposed_patch": proposed_diff,
        "verdict": "PASS — graph exposes Inspector override, fix is derivable",
    }
    OUT.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
    print(f"[record] wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
