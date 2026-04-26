"""Extract verified ground-truth answers for the bake-off questions.

We must be able to point to file:line for every fact. If a fact can't
be verified directly from the source, it does not become a question.
"""
from __future__ import annotations

import json
from pathlib import Path

from unitygraph.build.graph import Graph
from unitygraph.mcp import queries

GRAPH = Graph.load(Path("D:/PR/Unity/clash.io/graph-out/graph.json"))
PROJECT_ROOT = Path("D:/PR/Unity/clash.io")


def q1_enemy_controller_spawn() -> dict:
    """Tier 1 — pure code: what does EnemyController.SpawnEnemy() do?"""
    file = PROJECT_ROOT / "Assets/_Assets/Scripts/Enemy/EnemyController.cs"
    text = file.read_text(encoding="utf-8")
    # Locate SpawnEnemy method
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if "SpawnEnemy" in line and "(" in line), None
    )
    body = []
    if start is not None:
        depth = 0
        for line in lines[start:]:
            body.append(line)
            depth += line.count("{") - line.count("}")
            if depth == 0 and "{" in "".join(body):
                break
    return {
        "id": "q1",
        "tier": 1,
        "question": "What does EnemyController.SpawnEnemy() do? Summarize in one sentence.",
        "ground_truth": "Calls EnemyDatabase.GetRandomEnemy(), pools an instance, parents it, calls EnemyBase.Spawn() on it.",
        "evidence_file": "Assets/_Assets/Scripts/Enemy/EnemyController.cs",
        "evidence_lines": list(range(start + 1, start + len(body) + 1)) if start else [],
        "method_body_first_line": start + 1 if start is not None else 0,
    }


def q2_enemybase_inheritance() -> dict:
    """Tier 1 — class inheritance."""
    file = PROJECT_ROOT / "Assets/_Assets/Scripts/Enemy/EnemyBase.cs"
    text = file.read_text(encoding="utf-8")
    return {
        "id": "q2",
        "tier": 1,
        "question": "What class does EnemyBase inherit from?",
        "ground_truth": "MonoBehaviour",
        "evidence_file": "Assets/_Assets/Scripts/Enemy/EnemyBase.cs",
        "snippet": next(
            (line for line in text.splitlines() if "class EnemyBase" in line), ""
        ).strip(),
    }


def q3_who_calls_getcomponent_enemybase() -> dict:
    """Tier 2 — cross-file structural."""
    # From the survey: EnemyController has GetComponent<EnemyBase>
    matches = []
    for e in GRAPH.edges:
        if e.type == "depends_on" and e.data.get("via") == "GetComponent":
            for s in e.sites:
                if s.kind == "get_component" and "EnemyBase" in (s.snippet or ""):
                    from_node = next(
                        (n for n in GRAPH.nodes if n.id == e.from_id), None
                    )
                    if from_node:
                        matches.append(
                            {
                                "caller": from_node.data.get("name"),
                                "file": s.file,
                                "line": s.line,
                                "method": s.containing_method,
                                "snippet": s.snippet,
                            }
                        )
    return {
        "id": "q3",
        "tier": 2,
        "question": "Which scripts call GetComponent<EnemyBase>()? List each with the file path and method name.",
        "ground_truth": matches,
        "expected_count": len(matches),
    }


def q4_charactermbehaviour_calls_animator() -> dict:
    """Tier 2 — method calls between classes."""
    sites = []
    for e in GRAPH.edges:
        if e.type != "depends_on":
            continue
        from_node = next((n for n in GRAPH.nodes if n.id == e.from_id), None)
        to_node = next((n for n in GRAPH.nodes if n.id == e.to_id), None)
        if not from_node or not to_node:
            continue
        if (
            from_node.data.get("name") == "CharacterBehaviour"
            and to_node.data.get("name") == "CharacterAnimator"
        ):
            for s in e.sites:
                if s.kind == "method_call":
                    sites.append({"line": s.line, "snippet": s.snippet})
    return {
        "id": "q4",
        "tier": 2,
        "question": "How many distinct method calls does CharacterBehaviour make on CharacterAnimator?",
        "ground_truth_count": len(sites),
        "evidence": sites,
    }


def q5_inspector_override_enemycontroller() -> dict:
    """Tier 3 — scene-code gap. EnemyController has 3 scalar overrides
    on its scene attachment: spawnRadius (10 vs code 12), despawnRadius
    (12 vs 20), drawDebugRadius (1/true — same value, different format)."""
    result = queries.inspector_overrides_for(GRAPH, "EnemyController")
    scalar_overrides = []
    for att in result.get("attachments", []):
        for ov in att["overrides"]:
            if isinstance(ov["code_default"], (int, float, str, bool)) and isinstance(
                ov["inspector_value"], (int, float, str, bool)
            ):
                scalar_overrides.append(
                    {
                        "gameobject": att["gameobject"].get("name"),
                        "field": ov["field"],
                        "inspector_value": ov["inspector_value"],
                        "code_default": ov["code_default"],
                    }
                )
    return {
        "id": "q5",
        "tier": 3,
        "question": (
            "On the EnemyController in the game scene, what is the actual "
            "spawnRadius value at runtime, and does it match the code default?"
        ),
        "ground_truth": {
            "scene_value": 10,
            "code_default": "12f",
            "matches_default": False,
            "all_scalar_overrides": scalar_overrides,
        },
    }


def q6_unityevent_rateus() -> dict:
    """Tier 3 — UnityEvent wiring (scene-only)."""
    result = queries.event_listeners(GRAPH, "RateUsScript")
    listeners = []
    for lst in result.get("listeners", []):
        listeners.append(
            {
                "method": lst["method"],
                "field": lst["field"],
                "site_file": lst["sites"][0]["file"] if lst["sites"] else None,
                "site_line": lst["sites"][0]["line"] if lst["sites"] else None,
            }
        )
    methods = sorted({lst["method"] for lst in listeners})
    return {
        "id": "q6",
        "tier": 3,
        "question": "Which methods on RateUsScript are bound as UnityEvent listeners? (i.e., wired up via the Inspector, not invoked from code)",
        "ground_truth_methods": methods,
        "ground_truth_count": len(listeners),
        "evidence": listeners,
    }


def q7_missing_scripts() -> dict:
    """Tier 3 — would never be visible to grep."""
    result = queries.find_missing_scripts(GRAPH, min_attachments=10)
    high_impact = [
        {
            "guid": m["guid"][:8],
            "attachment_count": m["attachment_count"],
        }
        for m in result["missing_scripts"][:5]
    ]
    return {
        "id": "q7",
        "tier": 3,
        "question": "Are there any GameObjects in this project with broken/missing script references? How many?",
        "ground_truth_count": result["count"],
        "top_5_by_impact": high_impact,
    }


def q8_refactor_impact() -> dict:
    """Tier 4 — synthesis: rename CharacterAnimator method.

    The "what breaks" answer needs:
    * code callers (CharacterBehaviour → CharacterAnimator method_call sites)
    * UnityEvent listeners on CharacterAnimator (none in clash.io — that's a useful negative)
    * inheritance (no subclass)
    """
    method = "SetAnimation"  # multiple call sites in CharacterBehaviour
    file = PROJECT_ROOT / "Assets/_Assets/Scripts/Characters/CharacterAnimator.cs"
    if file.exists():
        text = file.read_text(encoding="utf-8")
        method_lines = [
            (i + 1, line)
            for i, line in enumerate(text.splitlines())
            if "public" in line and method + "(" in line
        ]
    else:
        method_lines = []

    # Code callers
    callers = []
    for e in GRAPH.edges:
        if e.type != "depends_on":
            continue
        for s in e.sites:
            if s.kind == "method_call" and method in (s.snippet or ""):
                from_node = next(
                    (n for n in GRAPH.nodes if n.id == e.from_id), None
                )
                if from_node:
                    callers.append(
                        {
                            "caller": from_node.data.get("name"),
                            "file": s.file,
                            "line": s.line,
                            "snippet": s.snippet,
                        }
                    )

    # UnityEvent listeners on CharacterAnimator.Run
    listeners_result = queries.event_listeners(GRAPH, "CharacterAnimator")
    listeners_for_method = [
        lst
        for lst in listeners_result.get("listeners", [])
        if lst.get("method") == method
    ]

    return {
        "id": "q8",
        "tier": 4,
        "question": (
            f"I want to rename `CharacterAnimator.{method}` to a different name. "
            "Will any UnityEvent wiring or other callers break? List everything that needs updating."
        ),
        "ground_truth": {
            "method_defined_at": method_lines,
            "code_callers": callers,
            "unityevent_listeners": listeners_for_method,
            "summary": (
                f"{len(callers)} code call site(s); "
                f"{len(listeners_for_method)} UnityEvent listener(s)"
            ),
        },
    }


def main() -> None:
    questions = [
        q1_enemy_controller_spawn(),
        q2_enemybase_inheritance(),
        q3_who_calls_getcomponent_enemybase(),
        q4_charactermbehaviour_calls_animator(),
        q5_inspector_override_enemycontroller(),
        q6_unityevent_rateus(),
        q7_missing_scripts(),
        q8_refactor_impact(),
    ]
    out = Path(__file__).parent / "groundtruth.json"
    out.write_text(json.dumps(questions, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {len(questions)} questions to {out}")
    for q in questions:
        print(f"  [Tier {q['tier']}] {q['id']}: {q['question'][:80]}…")


if __name__ == "__main__":
    main()
