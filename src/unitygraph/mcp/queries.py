"""Deterministic graph queries (v1.6.0).

These sit one abstraction level above ``tools.py``: they answer the
questions a Unity dev actually asks -- "who uses X?", "what's the blast
radius of changing Y?", "show me the Inspector overrides across all
attachments" -- and return results that include the underlying evidence
``sites`` when the graph carries them.

The goal is to be the *reference oracle* any AI agent queries before
refactoring. Every function here must:

* be pure (take a Graph, return JSON-serializable dict)
* never mutate the graph
* always report evidence (sites) when available, otherwise say so
  explicitly with an empty ``sites: []`` field
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from unitygraph.build.graph import Edge, Graph, Node

# Path prefixes that indicate third-party / package code a user typically
# does not own and cannot meaningfully refactor. Used to filter queries
# like ``find_singletons`` and ``find_missing_scripts`` so they default
# to showing only user-owned scripts.
#
# Matching is done on the path's relative parts (OS-normalized by splitting
# on both separators), not substring -- so a file named
# ``Assets/MyPluginsHelper.cs`` is NOT treated as third-party just because
# it contains the substring "Plugins".
_THIRD_PARTY_SEGMENTS: frozenset[str] = frozenset(
    {
        "Plugins",
        "Feel",
        "ThirdParty",
        "Third Party",
        "Standard Assets",
        "Samples",
        "Editor Default Resources",
        # TMP ships demo scripts in this subtree; they're rarely the user's.
        "Examples & Extras",
    }
)


def _split_path_parts(path: str) -> list[str]:
    """OS-agnostic split of a project-relative path into segments."""
    if not path:
        return []
    # Handle both Windows and POSIX separators regardless of where we run.
    normalized = path.replace("\\", "/")
    return [p for p in normalized.split("/") if p]


def _is_user_script(node: Node) -> bool:
    """True if ``node`` is a user-owned Script (editable by the developer).

    Criteria (all must hold):

    * Node type is Script
    * ``external`` is not True (placeholder for unresolved guids)
    * ``file_path`` is under ``Assets/`` or under a user-embedded
      ``Packages/<name>/`` -- not under ``Library/`` or a third-party
      asset-pack directory
    """
    if node.type != "Script":
        return False
    if node.data.get("external") is True:
        return False
    parts = _split_path_parts(str(node.data.get("file_path") or ""))
    if not parts:
        return False
    if "Library" in parts:
        return False
    if _THIRD_PARTY_SEGMENTS & set(parts):
        return False
    # Accept Assets/ and Packages/ (the latter for user-embedded packages;
    # Library/PackageCache is already filtered above).
    return parts[0] in {"Assets", "Packages"}


def _norm(name: str) -> str:
    return name.strip().lower()


def _resolve_script_ids(graph: Graph, script_name: str) -> list[str]:
    """Return Script node ids matching ``script_name`` (case-insensitive)."""
    ids = graph.script_ids_by_name(script_name)
    if ids:
        return ids
    key = _norm(script_name)
    return [
        n.id
        for n in graph.nodes
        if n.type == "Script" and _norm(str(n.data.get("name", ""))) == key
    ]


def _sites_json(edge: Edge) -> list[dict[str, Any]]:
    return [s.to_json() for s in edge.sites]


def who_uses(graph: Graph, script_name: str) -> dict[str, Any]:
    """Every inbound reference to ``script_name`` -- who depends on it?

    Covers four kinds of references, each with evidence sites when
    available:

    * ``attached_to`` -- scenes/prefabs attaching this script to a GameObject
    * ``depends_on`` -- other scripts calling ``GetComponent<Script>()``,
      ``FindObjectOfType<Script>()``, or methods on fields typed as it
    * ``inherits`` -- subclasses
    * ``subscribes_to`` -- UnityEvent listeners whose callback lands here
    """
    script_ids = _resolve_script_ids(graph, script_name)
    if not script_ids:
        return {"script_name": script_name, "found": False, "usages": []}

    script_id_set = set(script_ids)
    nodes_by_id = graph.nodes_by_id()

    attached: list[dict[str, Any]] = []
    depends: list[dict[str, Any]] = []
    inherits: list[dict[str, Any]] = []
    subscribes: list[dict[str, Any]] = []

    for edge in graph.edges:
        if edge.type == "attached_to" and edge.from_id in script_id_set:
            owner = nodes_by_id.get(edge.to_id)
            attached.append(
                {
                    "gameobject": owner.to_json() if owner else {"id": edge.to_id},
                    "sites": _sites_json(edge),
                    "inspector_values": edge.data.get("inspector_values") or {},
                }
            )
        elif edge.type == "depends_on" and edge.to_id in script_id_set:
            caller = nodes_by_id.get(edge.from_id)
            depends.append(
                {
                    "caller": caller.to_json() if caller else {"id": edge.from_id},
                    "via": edge.data.get("via"),
                    "sites": _sites_json(edge),
                }
            )
        elif edge.type == "inherits" and edge.to_id in script_id_set:
            sub = nodes_by_id.get(edge.from_id)
            inherits.append(
                {
                    "subclass": sub.to_json() if sub else {"id": edge.from_id},
                    "sites": _sites_json(edge),
                }
            )
        elif edge.type == "subscribes_to" and edge.to_id in script_id_set:
            listener = nodes_by_id.get(edge.from_id)
            subscribes.append(
                {
                    "listener": listener.to_json() if listener else {"id": edge.from_id},
                    "field": edge.data.get("field"),
                    "method": edge.data.get("method"),
                    "sites": _sites_json(edge),
                }
            )

    total = len(attached) + len(depends) + len(inherits) + len(subscribes)
    return {
        "script_name": script_name,
        "found": True,
        "script_ids": script_ids,
        "total_references": total,
        "attached_to": attached,
        "depended_on_by": depends,
        "inherited_by": inherits,
        "subscribed_to_by": subscribes,
    }


def impact_of(graph: Graph, script_name: str, *, hops: int = 2) -> dict[str, Any]:
    """Blast radius -- every node reachable *by* this script within ``hops``.

    Walks outbound ``depends_on`` + ``subscribes_to`` + ``inherits`` edges
    from each Script node, collecting reachable Scripts and GameObjects.
    Each entry carries the shortest hop distance and the edge type that
    first reached it -- useful for reviewing the scope of a refactor.
    """
    if hops < 1:
        hops = 1
    script_ids = _resolve_script_ids(graph, script_name)
    if not script_ids:
        return {"script_name": script_name, "found": False}

    nodes_by_id = graph.nodes_by_id()
    # Outbound-only adjacency: "if I change this, who breaks?"
    out_adj: dict[str, list[tuple[str, str, Edge]]] = defaultdict(list)
    for edge in graph.edges:
        if edge.type in {"depends_on", "subscribes_to", "inherits", "attached_to"}:
            out_adj[edge.from_id].append((edge.to_id, edge.type, edge))

    depth_by_id: dict[str, int] = {sid: 0 for sid in script_ids}
    first_edge_by_id: dict[str, tuple[str, str]] = {}  # id -> (parent, edge_type)
    frontier = list(script_ids)
    for _ in range(hops):
        next_frontier: list[str] = []
        for nid in frontier:
            for nbr, etype, _edge in out_adj.get(nid, ()):
                if nbr in depth_by_id:
                    continue
                depth_by_id[nbr] = depth_by_id[nid] + 1
                first_edge_by_id[nbr] = (nid, etype)
                next_frontier.append(nbr)
        frontier = next_frontier

    impacted: list[dict[str, Any]] = []
    for nid, depth in depth_by_id.items():
        if nid in script_ids:
            continue
        node = nodes_by_id.get(nid)
        if node is None:
            continue
        parent, etype = first_edge_by_id.get(nid, ("", ""))
        impacted.append(
            {
                "node": node.to_json(),
                "hops": depth,
                "reached_via": etype,
                "from": parent,
            }
        )
    impacted.sort(key=lambda r: (r["hops"], r["node"].get("type", "")))

    return {
        "script_name": script_name,
        "found": True,
        "script_ids": script_ids,
        "hops": hops,
        "impacted_count": len(impacted),
        "impacted": impacted,
    }


def find_singletons(
    graph: Graph,
    *,
    min_attachments: int = 2,
    user_only: bool = True,
) -> dict[str, Any]:
    """Scripts attached to ``min_attachments`` or more GameObjects.

    These are the "used everywhere" scripts -- changing them has
    disproportionate reach. Results carry the full set of attachment
    sites so an agent can decide whether a rename is safe.

    ``user_only`` (default True) restricts results to scripts the
    developer actually owns -- drops Unity built-ins (Image, Button,
    TextMeshPro, ...), third-party asset packs (Feel, Plugins, Standard
    Assets), and unresolved ``external`` placeholders. Set to False
    to see every script regardless of ownership -- useful when auditing
    a project you didn't write.
    """
    if min_attachments < 1:
        min_attachments = 1

    nodes_by_id = graph.nodes_by_id()
    attachments: dict[str, list[Edge]] = defaultdict(list)
    for edge in graph.edges:
        if edge.type == "attached_to":
            attachments[edge.from_id].append(edge)

    hits: list[dict[str, Any]] = []
    for node in graph.nodes:
        if node.type != "Script":
            continue
        if user_only and not _is_user_script(node):
            continue
        edges = attachments.get(node.id, [])
        if len(edges) < min_attachments:
            continue
        hits.append(
            {
                "script": node.to_json(),
                "attachment_count": len(edges),
                "attachments": [
                    {
                        "gameobject_id": e.to_id,
                        "gameobject_name": (
                            owner.data.get("name")
                            if (owner := nodes_by_id.get(e.to_id)) is not None
                            else None
                        ),
                        "scope": e.data.get("scope"),
                        "sites": _sites_json(e),
                    }
                    for e in edges
                ],
            }
        )
    hits.sort(key=lambda h: h["attachment_count"], reverse=True)
    return {
        "min_attachments": min_attachments,
        "count": len(hits),
        "singletons": hits,
    }


def inspector_overrides_for(graph: Graph, script_name: str) -> dict[str, Any]:
    """Every Inspector-tuned value for ``script_name`` across all attachments.

    An Inspector override is a field whose scene/prefab-stored value
    differs from the script's code-level default. This is exactly the
    context Claude Code can't see from the .cs file alone.
    """
    script_ids = _resolve_script_ids(graph, script_name)
    if not script_ids:
        return {"script_name": script_name, "found": False}

    nodes_by_id = graph.nodes_by_id()
    script_id_set = set(script_ids)

    # Resolve code-level defaults from the Script node.
    code_defaults: dict[str, Any] = {}
    for sid in script_ids:
        node = nodes_by_id.get(sid)
        if node is None:
            continue
        for f in node.data.get("fields") or []:
            code_defaults.setdefault(f.get("name"), f.get("default"))

    per_attachment: list[dict[str, Any]] = []
    for edge in graph.edges:
        if edge.type != "attached_to" or edge.from_id not in script_id_set:
            continue
        inspector = edge.data.get("inspector_values") or {}
        overrides: list[dict[str, Any]] = []
        for field, value in inspector.items():
            default = code_defaults.get(field)
            if _values_differ(default, value):
                overrides.append(
                    {
                        "field": field,
                        "inspector_value": value,
                        "code_default": default,
                    }
                )
        if not overrides:
            continue
        owner = nodes_by_id.get(edge.to_id)
        per_attachment.append(
            {
                "gameobject": owner.to_json() if owner else {"id": edge.to_id},
                "scope": edge.data.get("scope"),
                "overrides": overrides,
                "sites": _sites_json(edge),
            }
        )

    return {
        "script_name": script_name,
        "found": True,
        "code_defaults": code_defaults,
        "overridden_attachments": len(per_attachment),
        "attachments": per_attachment,
    }


def _values_differ(default: Any, inspector: Any) -> bool:
    if default is None:
        # Can't decide -- treat anything non-default-looking as an override.
        return inspector not in (None, "", 0, 0.0, False, [])
    a = str(default).rstrip("f").rstrip("F")
    b = str(inspector).rstrip("f").rstrip("F")
    if a == b:
        return False
    try:
        return abs(float(a) - float(b)) > 1e-9
    except (TypeError, ValueError):
        return True


def field_wiring(graph: Graph, script_name: str, field_name: str) -> dict[str, Any]:
    """Every place ``script_name.field_name`` is wired in scenes/prefabs.

    Covers UnityEvent wiring (``subscribes_to`` whose data.field matches)
    and Inspector references. Useful when refactoring a field -- the call
    sites in code are easy to find, but UnityEvent listeners live in YAML.
    """
    script_ids = _resolve_script_ids(graph, script_name)
    if not script_ids:
        return {"script_name": script_name, "field_name": field_name, "found": False}
    script_id_set = set(script_ids)

    wirings: list[dict[str, Any]] = []
    nodes_by_id = graph.nodes_by_id()
    for edge in graph.edges:
        if edge.type != "subscribes_to":
            continue
        # The listener holds the field; the target is the callback receiver.
        if edge.from_id not in script_id_set:
            continue
        if edge.data.get("field") != field_name:
            continue
        target = nodes_by_id.get(edge.to_id)
        wirings.append(
            {
                "target": target.to_json() if target else {"id": edge.to_id},
                "method": edge.data.get("method"),
                "mode": edge.data.get("mode"),
                "sites": _sites_json(edge),
            }
        )
    return {
        "script_name": script_name,
        "field_name": field_name,
        "found": True,
        "wiring_count": len(wirings),
        "wirings": wirings,
    }


def event_listeners(graph: Graph, script_name: str) -> dict[str, Any]:
    """All UnityEvent callbacks landing on methods of ``script_name``."""
    script_ids = _resolve_script_ids(graph, script_name)
    if not script_ids:
        return {"script_name": script_name, "found": False}
    script_id_set = set(script_ids)

    nodes_by_id = graph.nodes_by_id()
    listeners: list[dict[str, Any]] = []
    for edge in graph.edges:
        if edge.type != "subscribes_to" or edge.to_id not in script_id_set:
            continue
        src = nodes_by_id.get(edge.from_id)
        listeners.append(
            {
                "from_script": src.to_json() if src else {"id": edge.from_id},
                "field": edge.data.get("field"),
                "method": edge.data.get("method"),
                "sites": _sites_json(edge),
            }
        )
    return {
        "script_name": script_name,
        "found": True,
        "listener_count": len(listeners),
        "listeners": listeners,
    }


def find_missing_scripts(graph: Graph, *, min_attachments: int = 1) -> dict[str, Any]:
    """Script nodes marked ``external=true`` -- script_guid referenced but
    no matching .cs found.

    These usually indicate:
    * a prefab/scene that references a deleted script (the classic
      Unity "Missing script (Mono Script)" warning), or
    * a third-party package script that was stripped or renamed.

    ``min_attachments`` filters out placeholders with no live attachments
    (stale guids that won't actually show up in the Unity Editor). Default
    is 1 -- only report placeholders that are actually referenced by at
    least one GameObject.
    """
    if min_attachments < 0:
        min_attachments = 0

    placeholders: list[Node] = [
        n for n in graph.nodes if n.type == "Script" and n.data.get("external") is True
    ]
    # For each placeholder, list the GameObjects it's attached to.
    attachments: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        if edge.type == "attached_to":
            attachments[edge.from_id].append(edge.to_id)

    nodes_by_id = graph.nodes_by_id()
    out: list[dict[str, Any]] = []
    for n in placeholders:
        targets = attachments.get(n.id, [])
        if len(targets) < min_attachments:
            continue
        out.append(
            {
                "script_id": n.id,
                "guid": n.data.get("guid"),
                "suspected_path": n.data.get("file_path"),
                "attached_to": [
                    owner.to_json()
                    if (owner := nodes_by_id.get(gid)) is not None
                    else {"id": gid}
                    for gid in targets
                ],
                "attachment_count": len(targets),
            }
        )
    out.sort(key=lambda r: r["attachment_count"], reverse=True)
    return {"count": len(out), "missing_scripts": out}
