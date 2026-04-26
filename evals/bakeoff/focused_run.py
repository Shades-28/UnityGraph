"""Focused 8-question bake-off across all three projects.

The 8 questions chosen are the ones that meaningfully differentiated
UnityGraph from baseline on clash.io. Run them on LargeProject and
MidsizeProject to see if the result holds at scale.

Each question has a deterministic UnityGraph answer. The baseline
"answer" is a *cost estimate* -- how many tool calls (grep/read/glob)
a Claude agent would need to produce the same answer, and whether
the answer would be confidently correct, hedged, or wrong.

Cost estimates are rough; signal is in the verdict per question, not
the absolute number.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

from unitygraph.build.graph import Graph
from unitygraph.mcp import queries

# Override via UNITYGRAPH_EVAL_ROOT to point at your local Unity-project corpus.
# Default works on the original author's machine; everyone else must set the var.
EVAL_ROOT = Path(os.environ.get("UNITYGRAPH_EVAL_ROOT", "D:/PR/Unity"))
PROJECTS = {
    "clash.io": EVAL_ROOT / "clash.io",
    "MidsizeProject": EVAL_ROOT / "MidsizeProject",
    "LargeProject": EVAL_ROOT / "LargeProject",
}


def _project_pretty(name: str) -> str:
    return f"\n{'#' * 70}\n# {name}\n{'#' * 70}"


def run_project(name: str, root: Path) -> dict:
    print(_project_pretty(name))
    g = Graph.load(root / "graph-out" / "graph.json")

    out: dict = {"project": name}

    # Q5-style -- Inspector overrides (find a script with the most scalar overrides)
    print("\n--- Q5: Inspector overrides ---")
    user = [n for n in g.nodes if queries._is_user_script(n)]
    best_script = None
    best_count = 0
    for n in user[:200]:
        r = queries.inspector_overrides_for(g, n.data["name"])
        if not r.get("found"):
            continue
        scalar = sum(
            1
            for att in r["attachments"]
            for ov in att["overrides"]
            if isinstance(ov.get("inspector_value"), (int, float, str, bool))
            and isinstance(ov.get("code_default"), (int, float, str, bool))
        )
        if scalar > best_count:
            best_count = scalar
            best_script = n.data["name"]
    print(f"  best script with scalar overrides: {best_script} ({best_count} overrides)")
    out["q5_inspector"] = {"script": best_script, "scalar_overrides": best_count}

    # Q6-style -- UnityEvent listeners
    print("\n--- Q6: UnityEvent landings ---")
    listener_totals = []
    for n in user[:300]:
        r = queries.event_listeners(g, n.data["name"])
        if r.get("found") and r["listener_count"] > 0:
            listener_totals.append((n.data["name"], r["listener_count"]))
    listener_totals.sort(key=lambda x: -x[1])
    print(f"  total scripts targeted by UnityEvents: {len(listener_totals)}")
    for name, cnt in listener_totals[:5]:
        print(f"    {name}: {cnt} bindings")
    out["q6_unityevent_targets"] = {
        "scripts_targeted": len(listener_totals),
        "top": listener_totals[:5],
    }

    # Q7 -- missing scripts
    print("\n--- Q7: missing scripts ---")
    missing = queries.find_missing_scripts(g, min_attachments=10)
    print(f"  missing-script placeholders with >=10 attachments: {missing['count']}")
    out["q7_missing"] = {"count": missing["count"]}

    # Q8/Q15 -- inheritance: subclasses of any user-base
    print("\n--- Q8/Q15: user-base inheritance pairs ---")
    user_names = {n.data.get("name") for n in user}
    inh_pairs = [
        (n.data.get("name"), n.data.get("base_class"))
        for n in user
        if n.data.get("base_class") in user_names
        and n.data.get("base_class") not in {"Editor"}
    ]
    print(f"  user-base inheritance pairs: {len(inh_pairs)}")
    out["q8_inheritance_pairs"] = len(inh_pairs)

    # Q10 -- List<UserType> field declarations
    print("\n--- Q10: List<UserType> ---")
    list_user_count = 0
    for n in user:
        for f in n.data.get("fields") or []:
            t = str(f.get("type") or "")
            if t.startswith("List<") and t.endswith(">"):
                inner = t[5:-1]
                if inner in user_names:
                    list_user_count += 1
    print(f"  List<UserType> field declarations: {list_user_count}")
    out["q10_list_usertype"] = list_user_count

    # Q13 -- most-attached user script -- how many distinct scopes?
    print("\n--- Q13: scopes for top user-singleton ---")
    sing = queries.find_singletons(g, min_attachments=2, user_only=True)
    if sing["singletons"]:
        top = sing["singletons"][0]
        scopes = {a["scope"] for a in top["attachments"] if a.get("scope")}
        print(f"  top user singleton: {top['script']['name']}")
        print(f"  attachments: {top['attachment_count']}, distinct scopes: {len(scopes)}")
        out["q13_top_singleton"] = {
            "name": top["script"]["name"],
            "attachments": top["attachment_count"],
            "scopes": len(scopes),
        }
    else:
        print("  no user singletons")
        out["q13_top_singleton"] = None

    # Q15 -- pick the heaviest-used user-base inheritance pair
    print("\n--- Q15: subclasses of a user base ---")
    base_to_subs = defaultdict(list)
    for child, parent in inh_pairs:
        base_to_subs[parent].append(child)
    if base_to_subs:
        biggest_base = max(base_to_subs, key=lambda k: len(base_to_subs[k]))
        subs = base_to_subs[biggest_base]
        print(f"  base class with most user subclasses: {biggest_base} -> {len(subs)} subclasses")
        for s in subs[:5]:
            print(f"    {s}")
        out["q15_inheritance"] = {"base": biggest_base, "subclass_count": len(subs)}
    else:
        out["q15_inheritance"] = None

    # Q16 -- string-based dispatch (UnityGraph CAN'T track this -- honest)
    print("\n--- Q16: string-based dispatch (UnityGraph: out-of-scope) ---")
    out["q16"] = "out-of-scope (UnityGraph honest)"

    return out


def main() -> None:
    results = []
    for name, root in PROJECTS.items():
        gp = root / "graph-out" / "graph.json"
        if not gp.exists():
            print(f"\n[SKIP {name}: no graph at {gp}]")
            continue
        try:
            r = run_project(name, root)
            results.append(r)
        except Exception as exc:
            print(f"\n[ERROR {name}: {exc}]")
    out = Path(__file__).parent / "focused_results.json"
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
