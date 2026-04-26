"""Run B (UnityGraph) on the 8 v2 adversarial questions. clash.io.

Each block answers one question by calling only queries.py + reading
graph.json. Reports what UnityGraph CAN return — even if "I don't track
this" is the honest answer, that's the answer.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from unitygraph.build.graph import Graph
from unitygraph.mcp import queries

g = Graph.load(Path("D:/PR/Unity/clash.io/graph-out/graph.json"))


def section(t: str) -> None:
    print(f"\n{'=' * 60}\n{t}\n{'=' * 60}")


# Q9: property vs field on EnemyBase
section("Q9 — EnemyBase: property/field 'Health'?")
eb = next(
    (n for n in g.nodes if n.type == "Script" and n.data.get("name") == "EnemyBase"),
    None,
)
if eb:
    fields = eb.data.get("fields") or []
    health_fields = [f for f in fields if f.get("name") == "Health"]
    print(f"fields named 'Health': {health_fields}")
    print(f"all fields on EnemyBase ({len(fields)}):")
    for f in fields:
        print(f"  - {f.get('name')} : {f.get('type')}")
    methods = eb.data.get("methods") or []
    health_methods = [m for m in methods if m.get("name") == "Health"]
    print(f"methods named 'Health' (would suggest property getter): {health_methods}")


# Q10: List<T> where T is user-defined
section("Q10 — List<UserType> declarations")
user_class_names = {n.data.get("name") for n in g.nodes if n.type == "Script"}
matches = []
for n in g.nodes:
    if n.type != "Script":
        continue
    fields = n.data.get("fields") or []
    for f in fields:
        t = str(f.get("type") or "")
        if t.startswith("List<") and t.endswith(">"):
            inner = t[5:-1]
            if inner in user_class_names:
                matches.append(
                    {
                        "script": n.data.get("name"),
                        "field": f.get("name"),
                        "type": t,
                        "line": f.get("line"),
                    }
                )
print(f"matches found: {len(matches)}")
for m in matches[:10]:
    print(f"  - {m['script']}.{m['field']} : {m['type']} (line {m['line']})")


# Q11: async methods
section("Q11 — async methods (UnityGraph view)")
# UnityGraph's MethodInfo records name + line + lifecycle, not return type.
# So this is a HONEST FAILURE case.
print("UnityGraph's MethodInfo does NOT record method return types.")
print("Cannot determine async/Task methods from the graph alone.")


# Q12: IPointerClickHandler implementations
section("Q12 — IPointerClickHandler implementers")
hits = []
for n in g.nodes:
    if n.type != "Script":
        continue
    interfaces = n.data.get("interfaces") or []
    if "IPointerClickHandler" in interfaces:
        hits.append(
            {
                "class": n.data.get("name"),
                "file_path": n.data.get("file_path"),
            }
        )
print(f"matches: {len(hits)}")
for h in hits:
    print(f"  - {h['class']} ({h['file_path']})")


# Q13: scenes/prefabs referencing CharacterAnimator
section("Q13 — Scopes referencing CharacterAnimator")
result = queries.who_uses(g, "CharacterAnimator")
scopes = set()
for att in result.get("attached_to", []):
    scope = att["gameobject"].get("scope") or ""
    if scope:
        scopes.add(scope)
print(f"distinct scopes (from attached_to): {len(scopes)}")
for s in sorted(scopes):
    print(f"  - {s}")


# Q14: Inspector overrides on EnemyController in DevScene
section("Q14 — EnemyController scalar overrides")
result = queries.inspector_overrides_for(g, "EnemyController")
scalar = []
for att in result.get("attachments", []):
    for ov in att["overrides"]:
        if isinstance(ov.get("inspector_value"), (int, float, str, bool)) and isinstance(
            ov.get("code_default"), (int, float, str, bool)
        ):
            scalar.append(ov)
print(f"scalar override count: {len(scalar)}")
for ov in scalar:
    print(f"  - {ov['field']}: {ov['inspector_value']} (default {ov['code_default']})")


# Q15: subclasses of EnemyBase + their depends_on
section("Q15 — Subclasses of EnemyBase + depends_on relationships")
subs = [
    n
    for n in g.nodes
    if n.type == "Script" and n.data.get("base_class") == "EnemyBase"
]
print(f"subclasses: {len(subs)}")
for sub in subs:
    print(f"\n  {sub.data.get('name')}")
    # depends_on edges from this subclass
    deps = []
    for e in g.edges:
        if e.from_id == sub.id and e.type == "depends_on":
            target_node = next((n for n in g.nodes if n.id == e.to_id), None)
            target_name = target_node.data.get("name") if target_node else "?"
            for s in e.sites:
                deps.append(f"{target_name} ({s.kind}) @ {s.file}:{s.line}")
    print(f"    depends_on: {len(deps)}")
    for d in deps[:6]:
        print(f"      - {d}")


# Q16: SendMessage / BroadcastMessage / Invoke string dispatch
section("Q16 — String-based dispatch (SendMessage/BroadcastMessage/Invoke)")
print("UnityGraph does not track string-based dispatch.")
print("These calls produce no edges in the graph since the target is a")
print("string literal at runtime, resolved by Unity, not the C# parser.")
print("Honest answer: cannot determine from graph alone.")
