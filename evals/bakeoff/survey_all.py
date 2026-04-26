"""Survey all three projects to surface concrete bake-off targets:
* number of user-script classes, GameObject scopes, prefabs
* example inheritance chains (depth >= 2)
* generic methods we can ask about
* extension methods
* properties (vs fields) -- UnityGraph weak spot
* partial classes
* async / Task methods
* interface implementations
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path

from unitygraph.build.graph import Graph
from unitygraph.mcp import queries

EVAL_ROOT = Path(os.environ.get("UNITYGRAPH_EVAL_ROOT", "D:/PR/Unity"))
PROJECTS = {
    "clash.io": EVAL_ROOT / "clash.io",
    "MidsizeProject": EVAL_ROOT / "MidsizeProject",
    "LargeProject": EVAL_ROOT / "LargeProject",
}


def is_user_game_script(node) -> bool:
    """User-owned script in the project's main game-code area."""
    if not queries._is_user_script(node):
        return False
    fp = str(node.data.get("file_path", "")).replace("\\", "/")
    # Heuristic: top-level Assets/Scripts or _Assets/Scripts
    return any(
        seg in fp
        for seg in (
            "_Assets/Scripts",
            "Assets/Scripts/",
            "/Game/",
            "/Game.cs",
        )
    )


def survey(name: str, root: Path) -> None:
    print(f"\n{'=' * 70}\n{name}  ({root})\n{'=' * 70}")
    graph_path = root / "graph-out" / "graph.json"
    if not graph_path.exists():
        print(f"  [no graph yet at {graph_path}]")
        return
    g = Graph.load(graph_path)

    user_scripts = [n for n in g.nodes if queries._is_user_script(n)]
    game_scripts = [n for n in g.nodes if is_user_game_script(n)]
    print(f"user scripts: {len(user_scripts)}  | game scripts (heuristic): {len(game_scripts)}")

    # Inheritance depth (>= 1 means has a user-class base, not just MonoBehaviour)
    user_names = {n.data.get("name") for n in user_scripts}
    chains = []
    for n in user_scripts:
        bc = n.data.get("base_class")
        if bc in user_names:
            chains.append((n.data.get("name"), bc))
    print(f"user-base inheritance pairs: {len(chains)}")
    for child, parent in chains[:5]:
        print(f"   {child} : {parent}")

    # Singletons of user-owned scripts (multi-attached)
    sing = queries.find_singletons(g, min_attachments=3, user_only=True)
    print(f"user singletons (>=3 attachments): {sing['count']}")
    for s in sing["singletons"][:3]:
        print(f"   {s['script']['name']}: {s['attachment_count']}x")

    # Inspector overrides count (how rich is the scene-code gap signal?)
    total_overrides = 0
    target_scripts = []
    for n in user_scripts[:60]:  # sample
        result = queries.inspector_overrides_for(g, n.data["name"])
        if result.get("found") and result.get("overridden_attachments"):
            scalar = sum(
                1
                for att in result["attachments"]
                for ov in att["overrides"]
                if isinstance(ov.get("inspector_value"), (int, float, str, bool))
                and isinstance(ov.get("code_default"), (int, float, str, bool))
            )
            if scalar:
                target_scripts.append((n.data["name"], scalar))
                total_overrides += scalar
    print(f"scripts w/ scalar Inspector overrides (sampled): {len(target_scripts)} ({total_overrides} overrides)")
    for name, count in sorted(target_scripts, key=lambda x: -x[1])[:5]:
        print(f"   {name}: {count} scalar override(s)")

    # UnityEvent landings -- every script that's a UnityEvent target
    listeners_per_script = defaultdict(int)
    for n in user_scripts:
        result = queries.event_listeners(g, n.data["name"])
        if result.get("found") and result["listener_count"] > 0:
            listeners_per_script[n.data["name"]] = result["listener_count"]
    print(f"scripts targeted by UnityEvent listeners: {len(listeners_per_script)}")
    for name, cnt in sorted(listeners_per_script.items(), key=lambda x: -x[1])[:5]:
        print(f"   {name}: {cnt} binding(s)")

    # Adversarial-feature scan: properties, async, extension methods, interfaces
    # Done by simple grep across game code dirs.
    feat = {"property": 0, "async_task": 0, "extension_method": 0, "interface_impl": 0, "partial_class": 0}
    for cs_path in root.rglob("*.cs"):
        rel = cs_path.relative_to(root).as_posix()
        if any(skip in rel for skip in ("/Library/", "/Temp/", "/Plugins/", "/Feel/", "/vFolders/", "/vHierarchy/", "/Editor/")):
            continue
        try:
            text = cs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"\bget\s*;\s*set\s*;", text) or re.search(r"=>\s*\w", text):
            feat["property"] += 1
        if "async Task" in text or "async void" in text:
            feat["async_task"] += 1
        if re.search(r"public static \w+ \w+\s*\(\s*this ", text):
            feat["extension_method"] += 1
        if re.search(r"class \w+\s*:\s*[\w<>,\s]*I[A-Z]\w+", text):
            feat["interface_impl"] += 1
        if re.search(r"\bpartial\s+class\b", text):
            feat["partial_class"] += 1
    print(f"feature presence (files containing): {feat}")

    # Missing scripts
    missing = queries.find_missing_scripts(g, min_attachments=10)
    print(f"missing scripts (>=10 attachments): {missing['count']}")


def main() -> None:
    for name, root in PROJECTS.items():
        survey(name, root)


if __name__ == "__main__":
    main()
