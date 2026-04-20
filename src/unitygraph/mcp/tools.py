"""Pure-Python graph query layer underlying the MCP tools.

Keeping the logic separate from the MCP transport lets us unit-test every
tool without spinning up an actual MCP server. The server module
(``unitygraph.mcp.server``) is a thin wrapper that exposes these functions
as MCP tools.

Naming:
* ``graph`` — the loaded ``Graph`` object.
* ``name`` parameters match how a developer refers to things in a task
  (GameObject name, script class name, prefab name). Matching is
  case-insensitive and tolerant of spaces.
"""

from __future__ import annotations

from typing import Any

from unitygraph.build.graph import Graph


def _norm(name: str) -> str:
    return name.strip().lower()


def _gameobject_nodes(graph: Graph, name: str) -> list[dict[str, Any]]:
    key = _norm(name)
    return [
        n.to_json()
        for n in graph.nodes
        if n.type == "GameObject" and _norm(n.data.get("name", "")) == key
    ]


def _script_nodes(graph: Graph, name: str) -> list[dict[str, Any]]:
    key = _norm(name)
    return [
        n.to_json()
        for n in graph.nodes
        if n.type == "Script" and _norm(n.data.get("name", "")) == key
    ]


def _component_nodes_on(graph: Graph, gameobject_id: str) -> list[dict[str, Any]]:
    """Components (built-in and script) attached to ``gameobject_id``."""
    nodes_by_id = graph.nodes_by_id()
    owners: list[dict[str, Any]] = []
    for edge in graph.edges:
        if edge.type != "attached_to" or edge.to_id != gameobject_id:
            continue
        node = nodes_by_id.get(edge.from_id)
        if node is None:
            continue
        entry = node.to_json()
        if edge.data.get("inspector_values"):
            entry = {**entry, "inspector_values": edge.data["inspector_values"]}
        owners.append(entry)
    return owners


def get_components(graph: Graph, gameobject_name: str) -> dict[str, Any]:
    """List all components attached to ``gameobject_name`` across every scope.

    Returns one entry per matching GameObject (a name can appear in multiple
    scenes/prefabs).
    """
    matches = _gameobject_nodes(graph, gameobject_name)
    if not matches:
        return {"gameobject_name": gameobject_name, "matches": []}

    results: list[dict[str, Any]] = []
    for go in matches:
        components = _component_nodes_on(graph, go["id"])
        script_types = [c.get("name") for c in components if c.get("type") == "Script"]
        component_types = [
            c.get("component_type") for c in components if c.get("type") == "Component"
        ]
        results.append(
            {
                "gameobject": go,
                "component_count": len(components),
                "scripts": script_types,
                "components": component_types,
                "detail": components,
            }
        )
    return {"gameobject_name": gameobject_name, "matches": results}


def get_inspector_values(graph: Graph, component_name: str, gameobject_name: str) -> dict[str, Any]:
    """Inspector-set values for ``component_name`` on ``gameobject_name``.

    For scripts this is the source of truth — Inspector values override
    code defaults, which is exactly the context Claude Code usually lacks.
    """
    go_matches = _gameobject_nodes(graph, gameobject_name)
    if not go_matches:
        return {
            "gameobject_name": gameobject_name,
            "component_name": component_name,
            "found": False,
            "reason": f"no GameObject named {gameobject_name!r} in the graph",
        }

    key = _norm(component_name)
    results: list[dict[str, Any]] = []
    for go in go_matches:
        components = _component_nodes_on(graph, go["id"])
        for comp in components:
            if comp.get("type") == "Script" and _norm(comp.get("name", "")) == key:
                inspector = comp.get("inspector_values") or {}
                code_defaults = {f.get("name"): f.get("default") for f in comp.get("fields") or []}
                overrides = []
                for field_name, inspector_value in inspector.items():
                    default = code_defaults.get(field_name)
                    if default is not None and str(default).rstrip("f") not in {
                        str(inspector_value),
                        str(int(inspector_value))
                        if isinstance(inspector_value, float) and inspector_value.is_integer()
                        else "",
                    }:
                        overrides.append(
                            {
                                "field": field_name,
                                "inspector_value": inspector_value,
                                "code_default": default,
                            }
                        )
                results.append(
                    {
                        "gameobject": go,
                        "component_type": "Script",
                        "script_name": comp.get("name"),
                        "inspector_values": inspector,
                        "code_defaults": code_defaults,
                        "overrides": overrides,
                    }
                )
            elif comp.get("type") == "Component" and _norm(comp.get("component_type", "")) == key:
                results.append(
                    {
                        "gameobject": go,
                        "component_type": comp.get("component_type"),
                        "inspector_values": comp.get("inspector_values") or {},
                    }
                )

    return {
        "gameobject_name": gameobject_name,
        "component_name": component_name,
        "found": bool(results),
        "matches": results,
    }


def get_scene_graph(graph: Graph, scene_name: str) -> dict[str, Any]:
    """Full GameObject list for ``scene_name`` (flat — hierarchy in I3)."""
    key = _norm(scene_name)
    scene_node = None
    for n in graph.nodes:
        if n.type == "Scene" and _norm(n.data.get("name", "")) == key:
            scene_node = n
            break
    if scene_node is None:
        return {"scene_name": scene_name, "found": False}

    scope = scene_node.id
    gos = [
        n.to_json() for n in graph.nodes if n.type == "GameObject" and n.data.get("scope") == scope
    ]
    return {
        "scene_name": scene_name,
        "found": True,
        "scene": scene_node.to_json(),
        "gameobjects": gos,
        "count": len(gos),
    }


def find_script_usages(graph: Graph, script_name: str) -> dict[str, Any]:
    """All GameObjects (across scenes + prefabs) that have ``script_name`` attached."""
    key = _norm(script_name)
    script_ids = {
        n.id for n in graph.nodes if n.type == "Script" and _norm(n.data.get("name", "")) == key
    }
    if not script_ids:
        return {"script_name": script_name, "found": False, "usages": []}

    usages: list[dict[str, Any]] = []
    go_by_id = {n.id: n for n in graph.nodes if n.type == "GameObject"}
    for edge in graph.edges:
        if edge.type != "attached_to" or edge.from_id not in script_ids:
            continue
        owner = go_by_id.get(edge.to_id)
        if owner is None:
            continue
        usages.append(
            {
                "gameobject": owner.to_json(),
                "inspector_values": edge.data.get("inspector_values") or {},
            }
        )
    return {"script_name": script_name, "found": True, "usages": usages, "count": len(usages)}


def get_prefab_chain(graph: Graph, prefab_name: str) -> dict[str, Any]:
    """Return the full variant inheritance chain for a prefab.

    Walks ``is_variant_of`` edges from the given prefab up to the root base.
    The chain is reported in order [variant, ..., base].
    """
    key = _norm(prefab_name)
    nodes_by_id = graph.nodes_by_id()
    matches = [
        n for n in graph.nodes if n.type == "Prefab" and _norm(str(n.data.get("name", ""))) == key
    ]
    if not matches:
        return {"prefab_name": prefab_name, "found": False, "chains": []}

    # Map source -> first is_variant_of target
    parent_of: dict[str, str] = {}
    overrides_by_from: dict[str, list[dict[str, Any]]] = {}
    for edge in graph.edges:
        if edge.type == "is_variant_of":
            parent_of.setdefault(edge.from_id, edge.to_id)
        elif edge.type == "overrides":
            overrides_by_from.setdefault(edge.from_id, []).append(
                {
                    "target_file_id": edge.data.get("target_file_id"),
                    "property_path": edge.data.get("property_path"),
                    "value": edge.data.get("value"),
                }
            )

    chains: list[dict[str, Any]] = []
    for leaf in matches:
        chain_ids: list[str] = [leaf.id]
        seen = {leaf.id}
        cur = leaf.id
        while cur in parent_of:
            nxt = parent_of[cur]
            if nxt in seen:  # cycle guard
                break
            chain_ids.append(nxt)
            seen.add(nxt)
            cur = nxt
        chain_nodes = [nodes_by_id[pid].to_json() for pid in chain_ids if pid in nodes_by_id]
        chains.append(
            {
                "chain": chain_nodes,
                "depth": len(chain_nodes),
                "overrides": overrides_by_from.get(leaf.id, []),
            }
        )
    return {"prefab_name": prefab_name, "found": True, "chains": chains}


def get_neighbors(graph: Graph, node_id: str, hops: int = 1) -> dict[str, Any]:
    """BFS from ``node_id`` out to ``hops`` depth, undirected over all edge types."""
    if hops < 0:
        hops = 0
    nodes_by_id = graph.nodes_by_id()
    if node_id not in nodes_by_id:
        # Try a case-insensitive name match as a fallback.
        key = _norm(node_id)
        candidate = next(
            (n for n in graph.nodes if _norm(str(n.data.get("name", ""))) == key),
            None,
        )
        if candidate is None:
            return {"node_id": node_id, "found": False, "neighbors": []}
        node_id = candidate.id

    # Build undirected adjacency on-demand.
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for edge in graph.edges:
        adjacency.setdefault(edge.from_id, []).append((edge.to_id, edge.type))
        adjacency.setdefault(edge.to_id, []).append((edge.from_id, edge.type))

    depth_by_id: dict[str, int] = {node_id: 0}
    frontier = [node_id]
    for _ in range(hops):
        next_frontier: list[str] = []
        for nid in frontier:
            for nbr, _edge_type in adjacency.get(nid, ()):
                if nbr not in depth_by_id:
                    depth_by_id[nbr] = depth_by_id[nid] + 1
                    next_frontier.append(nbr)
        frontier = next_frontier

    result_nodes = []
    for nid, depth in depth_by_id.items():
        if nid == node_id:
            continue
        node = nodes_by_id.get(nid)
        if node is None:
            continue
        entry = node.to_json()
        entry["_hop"] = depth
        result_nodes.append(entry)
    result_nodes.sort(key=lambda r: (r["_hop"], r.get("type", "")))

    return {
        "node_id": node_id,
        "found": True,
        "root": nodes_by_id[node_id].to_json() if node_id in nodes_by_id else None,
        "hops": hops,
        "neighbor_count": len(result_nodes),
        "neighbors": result_nodes,
    }


def shortest_path(graph: Graph, from_id: str, to_id: str) -> dict[str, Any]:
    """BFS shortest path between two nodes (undirected)."""
    nodes_by_id = graph.nodes_by_id()
    # Fallback: resolve either endpoint by name.
    resolved_from = _resolve_id(graph, from_id, nodes_by_id)
    resolved_to = _resolve_id(graph, to_id, nodes_by_id)
    if resolved_from is None or resolved_to is None:
        return {"found": False, "reason": "endpoint not in graph"}
    from_id = resolved_from
    to_id = resolved_to
    if from_id == to_id:
        return {"found": True, "path": [nodes_by_id[from_id].to_json()], "hops": 0}

    adjacency: dict[str, list[tuple[str, str]]] = {}
    for edge in graph.edges:
        adjacency.setdefault(edge.from_id, []).append((edge.to_id, edge.type))
        adjacency.setdefault(edge.to_id, []).append((edge.from_id, edge.type))

    prev: dict[str, tuple[str, str]] = {}
    seen = {from_id}
    queue: list[str] = [from_id]
    while queue:
        nid = queue.pop(0)
        if nid == to_id:
            break
        for nbr, etype in adjacency.get(nid, ()):
            if nbr in seen:
                continue
            seen.add(nbr)
            prev[nbr] = (nid, etype)
            queue.append(nbr)

    if to_id not in seen:
        return {"found": False, "reason": "no path"}

    # Reconstruct
    path_ids: list[str] = [to_id]
    edge_types: list[str] = []
    cur = to_id
    while cur in prev:
        parent, etype = prev[cur]
        path_ids.append(parent)
        edge_types.append(etype)
        cur = parent
    path_ids.reverse()
    edge_types.reverse()
    return {
        "found": True,
        "from": from_id,
        "to": to_id,
        "hops": len(path_ids) - 1,
        "path": [nodes_by_id[pid].to_json() for pid in path_ids if pid in nodes_by_id],
        "edge_types": edge_types,
    }


def query_graph(
    graph: Graph,
    natural_language_query: str,
    max_nodes: int = 50,
) -> dict[str, Any]:
    """Simple keyword + name matching against the graph.

    Extracts PascalCase/snake_case tokens from the query, matches them against
    node names, then returns the 2-hop neighborhood of the best matches,
    capped at ``max_nodes``. A real retrieval engine (entity-hop / task-type /
    full-neighborhood) lives in Layer 2 — this is the minimal MCP tool so
    Claude Code can reach the graph during early sessions.
    """
    import re

    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", natural_language_query))
    if not tokens:
        return {"query": natural_language_query, "tokens": [], "matches": []}
    lowered = {t.lower() for t in tokens}

    matched: list[str] = []
    for n in graph.nodes:
        name = str(n.data.get("name", ""))
        if name and name.lower() in lowered:
            matched.append(n.id)

    if not matched:
        return {"query": natural_language_query, "tokens": sorted(tokens), "matches": []}

    # 2-hop expansion, union across all matches.
    nodes_by_id = graph.nodes_by_id()
    adjacency: dict[str, list[str]] = {}
    for edge in graph.edges:
        adjacency.setdefault(edge.from_id, []).append(edge.to_id)
        adjacency.setdefault(edge.to_id, []).append(edge.from_id)

    seen: set[str] = set(matched)
    frontier = list(matched)
    for _ in range(2):
        next_frontier: list[str] = []
        for nid in frontier:
            for nbr in adjacency.get(nid, ()):
                if nbr not in seen:
                    seen.add(nbr)
                    next_frontier.append(nbr)
        frontier = next_frontier
        if len(seen) >= max_nodes:
            break

    sub_nodes = [nodes_by_id[nid].to_json() for nid in list(seen)[:max_nodes] if nid in nodes_by_id]
    return {
        "query": natural_language_query,
        "tokens": sorted(tokens),
        "seed_matches": matched,
        "nodes": sub_nodes,
        "node_count": len(sub_nodes),
    }


def _resolve_id(graph: Graph, maybe_id_or_name: str, nodes_by_id: dict[str, Any]) -> str | None:
    if maybe_id_or_name in nodes_by_id:
        return maybe_id_or_name
    key = _norm(maybe_id_or_name)
    for n in graph.nodes:
        if _norm(str(n.data.get("name", ""))) == key:
            return n.id
    return None


def get_event_connections(graph: Graph, gameobject_name: str) -> dict[str, Any]:
    """UnityEvent connections originating from or landing on ``gameobject_name``."""
    go_matches = _gameobject_nodes(graph, gameobject_name)
    if not go_matches:
        return {"gameobject_name": gameobject_name, "found": False, "connections": []}

    # Resolve: for every script attached to the GO, find subscribes_to edges.
    go_ids = {g["id"] for g in go_matches}

    # Map script_id -> list of (gameobject_id, scope) it's attached to.
    script_attachments: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.type == "attached_to":
            src = edge.from_id
            if src.startswith("script::"):
                script_attachments.setdefault(src, []).append(edge.to_id)

    outgoing: list[dict[str, Any]] = []
    incoming: list[dict[str, Any]] = []
    for edge in graph.edges:
        if edge.type != "subscribes_to":
            continue
        src_script = edge.from_id
        dst_script = edge.to_id
        src_attached = set(script_attachments.get(src_script, []))
        dst_attached = set(script_attachments.get(dst_script, []))
        if go_ids & src_attached:
            outgoing.append({"from_script": src_script, "to_script": dst_script, **edge.data})
        if go_ids & dst_attached:
            incoming.append({"from_script": src_script, "to_script": dst_script, **edge.data})

    return {
        "gameobject_name": gameobject_name,
        "found": True,
        "matches": [g for g in go_matches],
        "outgoing": outgoing,
        "incoming": incoming,
    }
