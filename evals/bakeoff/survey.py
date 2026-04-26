"""Survey clash.io for ground-truth bake-off targets.

Picks scripts that:
* live in _Assets/Scripts (real game code, not vendored asset packs)
* have meaningful relationships (depends_on, subscribes_to, attached_to)

Outputs candidates we can build questions around.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from unitygraph.build.graph import Graph
from unitygraph.mcp import queries

GRAPH_PATH = Path("D:/PR/Unity/clash.io/graph-out/graph.json")


def is_game_script(node) -> bool:
    fp = str(node.data.get("file_path", "")).replace("\\", "/")
    return node.type == "Script" and "_Assets/Scripts" in fp


def main() -> None:
    g = Graph.load(GRAPH_PATH)

    game_scripts = [n for n in g.nodes if is_game_script(n)]
    print(f"Game scripts in _Assets/Scripts: {len(game_scripts)}")

    # Top by attachments
    attach_count: dict[str, int] = defaultdict(int)
    for e in g.edges:
        if e.type == "attached_to":
            attach_count[e.from_id] += 1

    by_attach = sorted(
        game_scripts, key=lambda n: attach_count[n.id], reverse=True
    )
    print("\nTop 10 game scripts by attachment count:")
    for n in by_attach[:10]:
        print(f"  {attach_count[n.id]:>4}x  {n.data.get('name')}")

    # Subscribes_to within game scripts
    subs = [
        e
        for e in g.edges
        if e.type == "subscribes_to"
        and any(n.id == e.from_id and is_game_script(n) for n in g.nodes)
    ]
    print(f"\nUnityEvent wirings (subscribes_to from game scripts): {len(subs)}")

    # Depends_on among game scripts
    game_ids = {n.id for n in game_scripts}
    deps = [
        e
        for e in g.edges
        if e.type == "depends_on" and e.from_id in game_ids and e.to_id in game_ids
    ]
    print(f"Inter-game depends_on edges: {len(deps)}")
    for e in deps[:8]:
        from_name = next((n.data.get("name") for n in g.nodes if n.id == e.from_id), "?")
        to_name = next((n.data.get("name") for n in g.nodes if n.id == e.to_id), "?")
        sites = [s.kind for s in e.sites]
        print(f"  {from_name} -> {to_name}  via={e.data.get('via')}  sites={sites}")

    # Find one MonoBehaviour with overrides
    print("\nScripts with most Inspector-override attachments:")
    user_scripts = [n for n in game_scripts]
    override_counts = []
    for n in user_scripts:
        result = queries.inspector_overrides_for(g, n.data["name"])
        if result.get("found") and result.get("overridden_attachments", 0) > 0:
            override_counts.append((result["overridden_attachments"], n))
    override_counts.sort(key=lambda x: x[0], reverse=True)
    for cnt, n in override_counts[:8]:
        print(f"  {cnt:>3} attachments with overrides — {n.data.get('name')}")

    # Find missing scripts attached to GameObjects
    print("\nMissing scripts (top 5 by attachment):")
    missing = queries.find_missing_scripts(g)
    for m in missing["missing_scripts"][:5]:
        print(f"  guid={m['guid'][:8]}…  attachments={m['attachment_count']}  path={m['suspected_path']}")

    # Subscribes_to from game scripts — pick one with site
    print("\nGame-script UnityEvent wirings:")
    for e in g.edges:
        if e.type != "subscribes_to":
            continue
        from_node = next((n for n in g.nodes if n.id == e.from_id), None)
        to_node = next((n for n in g.nodes if n.id == e.to_id), None)
        if not from_node or not to_node:
            continue
        if not is_game_script(from_node) and not is_game_script(to_node):
            continue
        print(
            f"  {from_node.data.get('name')} -> {to_node.data.get('name')} "
            f".{e.data.get('method')}  field={e.data.get('field')}  "
            f"sites={len(e.sites)}"
        )


if __name__ == "__main__":
    main()
