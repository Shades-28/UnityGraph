"""Run B -- WITH UNITYGRAPH.

Answer each of the 8 bake-off questions using only the loaded
graph.json + the queries module. No file reading, no grep -- only
what UnityGraph offers.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from unitygraph.build.graph import Graph
from unitygraph.mcp import queries

EVAL_ROOT = Path(os.environ.get("UNITYGRAPH_EVAL_ROOT", "D:/PR/Unity"))
g = Graph.load(EVAL_ROOT / "clash.io" / "graph-out" / "graph.json")


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


# Q1 -- what does EnemyController.SpawnEnemy() do?
section("Q1 -- EnemyController.SpawnEnemy() body")
# UnityGraph stores method names + (after v1.4) call sites within methods,
# but NOT method bodies. Find the Script node:
ec = next(
    (n for n in g.nodes if n.type == "Script" and n.data.get("name") == "EnemyController"),
    None,
)
if ec:
    methods = ec.data.get("methods") or []
    spawn = next((m for m in methods if m.get("name") == "SpawnEnemy"), None)
    print(f"method record: {spawn}")
    # Outbound calls from EnemyController whose containing_method == SpawnEnemy
    sites_in_spawn = []
    for e in g.edges:
        if e.from_id != ec.id:
            continue
        for s in e.sites:
            if s.containing_method == "SpawnEnemy":
                sites_in_spawn.append(
                    {
                        "kind": s.kind,
                        "snippet": s.snippet,
                        "to": e.to_id.split("::")[1] if "::" in e.to_id else e.to_id,
                    }
                )
    print(f"call sites inside SpawnEnemy ({len(sites_in_spawn)}):")
    for s in sites_in_spawn:
        print(f"  - {s['kind']} -> {s['to']}: {s['snippet']}")


# Q2 -- EnemyBase inheritance
section("Q2 -- EnemyBase base class")
eb = next(
    (n for n in g.nodes if n.type == "Script" and n.data.get("name") == "EnemyBase"),
    None,
)
if eb:
    print(f"base_class: {eb.data.get('base_class')}")


# Q3 -- who calls GetComponent<EnemyBase>()
section("Q3 -- callers of GetComponent<EnemyBase>")
result = queries.who_uses(g, "EnemyBase")
gc_callers = []
for dep in result.get("depended_on_by", []):
    for site in dep.get("sites", []):
        if site["kind"] == "get_component":
            gc_callers.append(
                {
                    "caller": dep["caller"]["name"],
                    "file": site["file"],
                    "line": site["line"],
                    "method": site.get("containing_method"),
                    "snippet": site.get("snippet"),
                }
            )
for c in gc_callers:
    print(f"  - {c['caller']}.{c['method']} @ {c['file']}:{c['line']}")
    print(f"    {c['snippet']}")


# Q4 -- CharacterBehaviour -> CharacterAnimator method-call count
section("Q4 -- CharacterBehaviour method calls on CharacterAnimator")
count = 0
for e in g.edges:
    fn = next((n for n in g.nodes if n.id == e.from_id), None)
    tn = next((n for n in g.nodes if n.id == e.to_id), None)
    if not fn or not tn:
        continue
    if (
        fn.data.get("name") == "CharacterBehaviour"
        and tn.data.get("name") == "CharacterAnimator"
        and e.type == "depends_on"
    ):
        for s in e.sites:
            if s.kind == "method_call":
                count += 1
                print(f"  line {s.line}: {s.snippet}")
print(f"TOTAL method_call sites: {count}")


# Q5 -- spawnRadius Inspector override on EnemyController
section("Q5 -- EnemyController Inspector overrides (looking for spawnRadius)")
result = queries.inspector_overrides_for(g, "EnemyController")
for att in result.get("attachments", []):
    for ov in att["overrides"]:
        if isinstance(ov["code_default"], (int, float, str, bool)) and isinstance(
            ov["inspector_value"], (int, float, str, bool)
        ):
            print(
                f"  {att['gameobject']['name']}.{ov['field']} = "
                f"{ov['inspector_value']} (code default {ov['code_default']})"
            )


# Q6 -- UnityEvent listeners on RateUsScript
section("Q6 -- UnityEvent listeners on RateUsScript")
result = queries.event_listeners(g, "RateUsScript")
methods = sorted({lst["method"] for lst in result.get("listeners", [])})
print(f"distinct methods: {methods}")
print(f"total listener bindings: {result.get('listener_count')}")
for lst in result.get("listeners", []):
    site = (lst.get("sites") or [{}])[0]
    print(f"  - .{lst['method']} (field={lst.get('field')}) @ {site.get('file')}:{site.get('line')}")


# Q7 -- missing scripts
section("Q7 -- missing scripts")
result = queries.find_missing_scripts(g)
print(f"count: {result['count']}")
print("top 5 by attachment count:")
for m in result["missing_scripts"][:5]:
    print(f"  - guid={m['guid'][:8]}...  attached_to={m['attachment_count']} GameObjects")


# Q8 -- rename CharacterAnimator.SetAnimation
section("Q8 -- rename CharacterAnimator.SetAnimation impact")

# Code callers via depends_on edges with method_call sites mentioning SetAnimation
code_callers = []
for e in g.edges:
    if e.type != "depends_on":
        continue
    for s in e.sites:
        if s.kind == "method_call" and "SetAnimation" in (s.snippet or ""):
            fn = next((n for n in g.nodes if n.id == e.from_id), None)
            tn = next((n for n in g.nodes if n.id == e.to_id), None)
            if fn and tn and tn.data.get("name") == "CharacterAnimator":
                code_callers.append(
                    {
                        "caller": fn.data.get("name"),
                        "file": s.file,
                        "line": s.line,
                        "method": s.containing_method,
                        "snippet": s.snippet,
                    }
                )
print(f"code call sites on CharacterAnimator.SetAnimation: {len(code_callers)}")
for c in code_callers:
    print(f"  - {c['caller']}.{c['method']} @ {c['file']}:{c['line']}")

# UnityEvent listeners on SetAnimation
listeners = queries.event_listeners(g, "CharacterAnimator")
sa_listeners = [
    lst for lst in listeners.get("listeners", []) if lst.get("method") == "SetAnimation"
]
print(f"UnityEvent listeners on SetAnimation: {len(sa_listeners)}")
