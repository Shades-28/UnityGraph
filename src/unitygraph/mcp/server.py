"""MCP stdio server exposing UnityGraph query tools.

The server loads ``graph.json`` once at startup and answers tool calls from
in-memory state. All five I1 tools delegate to ``unitygraph.mcp.tools``;
the MCP layer is a thin adapter around that.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from unitygraph.build.graph import Graph
from unitygraph.mcp import tools as gtools


def build_server(graph_path: Path) -> FastMCP:
    graph = Graph.load(graph_path)
    server: FastMCP = FastMCP(
        name="unitygraph",
        instructions=(
            "Query the UnityGraph knowledge graph for a Unity project. "
            "Use these tools to look up GameObject components, Inspector-set "
            "field values, scene hierarchies, script usages, and UnityEvent "
            "connections before making assumptions about the scene."
        ),
    )

    @server.tool(description="List all components attached to a GameObject by name.")
    def get_components(gameobject_name: str) -> dict[str, Any]:
        return gtools.get_components(graph, gameobject_name)

    @server.tool(
        description=(
            "Return Inspector-set field values for a component on a GameObject. "
            "For scripts, also returns code defaults and flags any overrides — "
            "critical for distinguishing Inspector-tuned values from code literals."
        )
    )
    def get_inspector_values(component_name: str, gameobject_name: str) -> dict[str, Any]:
        return gtools.get_inspector_values(graph, component_name, gameobject_name)

    @server.tool(description="Get the full GameObject list for a scene by name.")
    def get_scene_graph(scene_name: str) -> dict[str, Any]:
        return gtools.get_scene_graph(graph, scene_name)

    @server.tool(description="Find all GameObjects that have a given script attached.")
    def find_script_usages(script_name: str) -> dict[str, Any]:
        return gtools.find_script_usages(graph, script_name)

    @server.tool(
        description=(
            "List UnityEvent connections for a GameObject — both outgoing (events this "
            "object fires) and incoming (callbacks listening on this object)."
        )
    )
    def get_event_connections(gameobject_name: str) -> dict[str, Any]:
        return gtools.get_event_connections(graph, gameobject_name)

    @server.tool(
        description=(
            "Return the prefab variant inheritance chain. Reports each step from the "
            "given prefab up to the base, plus any recorded field overrides."
        )
    )
    def get_prefab_chain(prefab_name: str) -> dict[str, Any]:
        return gtools.get_prefab_chain(graph, prefab_name)

    @server.tool(
        description=(
            "BFS N-hop neighborhood around a node id or name. Use this to see "
            "everything within 1-3 hops of a given entity."
        )
    )
    def get_neighbors(node_id: str, hops: int = 1) -> dict[str, Any]:
        return gtools.get_neighbors(graph, node_id, hops)

    @server.tool(
        description=(
            "Shortest path between two nodes (ids or names). Returns the node "
            "sequence and the edge types traversed."
        )
    )
    def shortest_path(from_id: str, to_id: str) -> dict[str, Any]:
        return gtools.shortest_path(graph, from_id, to_id)

    @server.tool(
        description=(
            "Simple natural-language graph query — extracts entity tokens from "
            "the text, finds matching nodes, returns their 2-hop subgraph. "
            "For token-budgeted retrieval (Layer 2), use inject_context instead."
        )
    )
    def query_graph(natural_language_query: str, max_nodes: int = 50) -> dict[str, Any]:
        return gtools.query_graph(graph, natural_language_query, max_nodes)

    @server.tool(
        description=(
            "Generate a task-specific UNITYGRAPH CONTEXT block. Given a task "
            "description (e.g., 'fix the slow on PlayerController'), returns a "
            "formatted subgraph under the given token budget that Claude Code "
            "can paste directly into its working context. Strategy is one of "
            "entity_hop / task_type / full_neighborhood, or auto (default)."
        )
    )
    def inject_context(
        task_text: str,
        strategy: str = "",
        hops: int = 2,
        budget: int = 1500,
    ) -> dict[str, Any]:
        from unitygraph.inject.engine import inject_context as _inject

        result = _inject(
            graph,
            task_text,
            strategy=strategy or None,  # type: ignore[arg-type]
            n_hops=hops,
            budget=budget,
        )
        return {
            "block": result.block,
            "strategy": result.strategy,
            "confidence": result.confidence,
            "token_count": result.token_count,
            "node_count": result.node_count,
            "edge_count": result.edge_count,
            "seed_node_ids": result.seed_node_ids,
        }

    return server


def run_stdio_server(graph_path: Path) -> None:
    server = build_server(graph_path)
    server.run(transport="stdio")
