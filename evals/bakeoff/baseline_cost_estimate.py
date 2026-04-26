"""For each question on each project, estimate baseline difficulty:

* feasibility: can grep+read alone produce the answer?
* tool calls: rough estimate of grep/read invocations needed
* failure modes: known reasons baseline gets wrong/incomplete answers

This is a pen-and-paper analysis, not literally running 100s of greps.
"""
import json
import os
from pathlib import Path

EVAL_ROOT = Path(os.environ.get("UNITYGRAPH_EVAL_ROOT", "D:/PR/Unity"))
PROJECTS = {
    "clash.io": EVAL_ROOT / "clash.io",
    "MidsizeProject": EVAL_ROOT / "MidsizeProject",
    "LargeProject": EVAL_ROOT / "LargeProject",
}


def cost(project: str) -> dict:
    """Per-project baseline cost analysis for the 7 focused questions."""
    return {
        "Q5_inspector_overrides": {
            "feasible": True,
            "calls": 4,  # find serialized fields, find scenes, grep each, compare
            "risk": "Easy to miss a scene; comparison logic by hand error-prone",
        },
        "Q6_unityevent_targets_count": {
            "feasible": True,
            "calls": 50 if project == "LargeProject" else 10,
            "risk": "For each user script, find guid, grep YAML -- 600+ scripts on LargeProject is hours",
        },
        "Q7_missing_scripts": {
            "feasible": False,
            "calls": "100+ (would need to enumerate all m_Script guids and cross-reference)",
            "risk": "Hedges or guesses; likely cannot answer correctly",
        },
        "Q10_list_usertype": {
            "feasible": True,
            "calls": 5,
            "risk": "Need to know all user class names first -- extra grep pass",
        },
        "Q13_top_singleton_scopes": {
            "feasible": True,
            "calls": 3,
            "risk": "find guid -> grep scenes/prefabs",
        },
        "Q15_inheritance_subclasses": {
            "feasible": True,
            "calls": 1,
            "risk": "1 grep gets the subclasses, but listing each subclass's depends_on requires reading each .cs",
        },
        "Q16_string_dispatch": {
            "feasible": True,
            "calls": 1,
            "risk": "Easy single grep -- UnityGraph CAN'T answer this; baseline wins",
        },
    }


def main() -> None:
    rows = []
    for project in PROJECTS:
        c = cost(project)
        rows.append({"project": project, "cost_estimate": c})
    out = Path(__file__).parent / "baseline_cost.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    for row in rows:
        print(f"\n=== {row['project']} ===")
        for q, info in row["cost_estimate"].items():
            print(f"  {q}: feasible={info['feasible']}, calls={info['calls']}")


if __name__ == "__main__":
    main()
