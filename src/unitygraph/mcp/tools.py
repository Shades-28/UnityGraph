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
