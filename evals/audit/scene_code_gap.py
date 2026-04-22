"""Audit: quantify the scene-code gap in real Unity projects.

For each graph.json, count the hidden-from-code-only evidence that
UnityGraph exposes but a code-only AI cannot see:

1. Inspector overrides — serialized fields where the scene/prefab value
   differs from the code default in the attached Script.
2. UnityEvent wirings — subscribes_to edges, which exist only in scene
   YAML's m_PersistentCalls (invisible in C# source).
3. Script attachments — Script nodes attached to GameObjects. A code-only
   reader knows the script exists; it doesn't know which scene instances
   use it.
4. Prefab variants with overrides — variant chains and per-field
   divergence, again invisible in source.
5. Execution-order overrides — MonoManager-set, not in source.

Print real numbers. No hand-waving.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def audit(graph_path: Path) -> dict:
    g = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes_by_id = {n["id"]: n for n in g["nodes"]}

    # Indices we'll need
    script_by_id: dict[str, dict] = {}
    code_defaults: dict[str, dict[str, str]] = {}  # script_id -> {field_name -> default literal}
    for n in g["nodes"]:
        if n["type"] == "Script":
            script_by_id[n["id"]] = n
            defaults = {}
            for f in n.get("fields") or []:
                if isinstance(f, dict) and f.get("name") and f.get("default") is not None:
                    defaults[f["name"]] = str(f["default"])
            code_defaults[n["id"]] = defaults

    # Counters
    inspector_overrides = []
    inspector_same_as_default = 0
    untracked_inspector_values = 0  # missing code defaults (e.g., external scripts)
    subscribes_to_edges = 0
    script_attachments = 0
    scenes_per_script: dict[str, set[str]] = defaultdict(set)
    attachments_per_script: Counter[str] = Counter()
    is_variant_of_edges = 0
    overrides_edges = 0
    execution_order_overrides = 0

    for n in g["nodes"]:
        if n["type"] == "Script" and "execution_order" in n and n["execution_order"] != 0:
            execution_order_overrides += 1

    for e in g["edges"]:
        if e["type"] == "attached_to":
            src = nodes_by_id.get(e["from"])
            dst = nodes_by_id.get(e["to"])
            if src and src["type"] == "Script" and dst and dst["type"] == "GameObject":
                script_attachments += 1
                attachments_per_script[src["id"]] += 1
                scope = dst.get("scope", "")
                scenes_per_script[src["id"]].add(scope)

                # Inspector values on the edge
                iv = e.get("inspector_values") or {}
                defaults = code_defaults.get(src["id"], {})
                script_rel_path = src.get("file_path", "")
                script_name = src.get("name", "")
                for field_name, scene_value in iv.items():
                    if not isinstance(scene_value, (int, float, str, bool)):
                        continue
                    default = defaults.get(field_name)
                    if default is None:
                        untracked_inspector_values += 1
                        continue
                    # Normalize "5.0f" vs 5.0 comparison
                    def_clean = default.rstrip("fF").strip()
                    try:
                        if float(def_clean) == float(scene_value):
                            inspector_same_as_default += 1
                            continue
                    except (TypeError, ValueError):
                        if def_clean == str(scene_value):
                            inspector_same_as_default += 1
                            continue
                    inspector_overrides.append(
                        {
                            "script": script_name,
                            "field": field_name,
                            "code_default": default,
                            "scene_value": scene_value,
                            "gameobject": dst.get("name"),
                            "scope": scope,
                            "script_file": script_rel_path,
                        }
                    )

        elif e["type"] == "subscribes_to":
            subscribes_to_edges += 1
        elif e["type"] == "is_variant_of":
            is_variant_of_edges += 1
        elif e["type"] == "overrides":
            overrides_edges += 1

    # Scripts used in multiple scenes (the "where is this used" signal Claude can't see)
    multi_scene_scripts = [
        (sid, len(scopes)) for sid, scopes in scenes_per_script.items() if len(scopes) > 1
    ]
    multi_scene_scripts.sort(key=lambda x: -x[1])

    return {
        "project": g.get("project_root", "?"),
        "stats": g.get("stats", {}),
        "inspector_overrides_count": len(inspector_overrides),
        "inspector_same_as_default_count": inspector_same_as_default,
        "untracked_inspector_values_count": untracked_inspector_values,
        "subscribes_to_edges": subscribes_to_edges,
        "script_attachments": script_attachments,
        "is_variant_of_edges": is_variant_of_edges,
        "overrides_edges": overrides_edges,
        "execution_order_overrides": execution_order_overrides,
        "scripts_attached_multiple_places": sum(1 for _, c in multi_scene_scripts),
        "top_multi_scene_scripts": [
            {"id": sid, "scopes": c, "name": nodes_by_id[sid]["name"]}
            for sid, c in multi_scene_scripts[:10]
        ],
        "sample_inspector_overrides": inspector_overrides[:15],
    }


def main() -> int:
    targets = [
        (
            "MiniUnityProject",
            Path(__file__).parents[2] / "fixtures/MiniUnityProject/graph-out/graph.json",
        ),
        (
            "Indian-Bike-Gangster",
            Path("C:/Users/aryan/AppData/Local/Temp/ug-indian-bike/graph.json"),
        ),
        ("clash.io", Path("C:/Users/aryan/AppData/Local/Temp/ug-clash/graph.json")),
        ("Graudation-Saga", Path("C:/Users/aryan/AppData/Local/Temp/ug-grad/graph.json")),
    ]

    for label, path in targets:
        if not path.exists():
            print(f"\n=== {label} — graph.json missing at {path}, skipping ===")
            continue
        print(f"\n{'=' * 72}")
        print(f" {label}")
        print(f" {path}")
        print(f"{'=' * 72}")
        result = audit(path)
        s = result["stats"]
        print(f"project:     {result['project']}")
        print(f"graph:       {s.get('n_nodes', '?'):,} nodes, {s.get('n_edges', '?'):,} edges")
        print()
        print(
            f"  Inspector overrides (scene value != code default):  {result['inspector_overrides_count']:,}"
        )
        print(
            f"  Inspector same-as-default:                          {result['inspector_same_as_default_count']:,}"
        )
        print(
            f"  Inspector values on fields w/o known defaults:      {result['untracked_inspector_values_count']:,}"
        )
        print(
            f"  UnityEvent subscribes_to edges:                     {result['subscribes_to_edges']:,}"
        )
        print(
            f"  Script attachments (script -> GO):                  {result['script_attachments']:,}"
        )
        print(
            f"  Prefab is_variant_of edges:                         {result['is_variant_of_edges']:,}"
        )
        print(
            f"  Prefab overrides edges:                             {result['overrides_edges']:,}"
        )
        print(
            f"  Script execution_order overrides:                   {result['execution_order_overrides']:,}"
        )
        print(
            f"  Scripts attached in >1 scope:                       {result['scripts_attached_multiple_places']:,}"
        )

        if result["sample_inspector_overrides"]:
            print("\n  Sample Inspector overrides (up to 15):")
            for o in result["sample_inspector_overrides"]:
                print(
                    f"    - {o['script']}.{o['field']}:  "
                    f"code={o['code_default']}  scene={o['scene_value']}  "
                    f"(on {o['gameobject']} in {o['scope']})"
                )
        if result["top_multi_scene_scripts"]:
            print("\n  Top scripts appearing in multiple scenes/prefabs:")
            for entry in result["top_multi_scene_scripts"]:
                print(f"    - {entry['name']:40}  in {entry['scopes']:3} scopes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
