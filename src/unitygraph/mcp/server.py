"""MCP stdio server exposing UnityGraph query tools.

The server holds a :class:`GraphRef` that auto-reloads ``graph.json`` when
the file changes on disk. That means a Stop/PostToolUse hook that runs
``unitygraph build . --update`` during a Claude Code session takes effect
on the *next* MCP tool call -- no server restart required.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from unitygraph.mcp import queries as gqueries
from unitygraph.mcp import tools as gtools
from unitygraph.mcp.graph_ref import GraphRef


def build_server(graph_path: Path) -> FastMCP:
    graph_ref = GraphRef(graph_path)
    server: FastMCP = FastMCP(
        name="unitygraph",
        instructions=(
            "Query the UnityGraph knowledge graph for a Unity project. "
            "Use these tools to look up GameObject components, Inspector-set "
            "field values, scene hierarchies, script usages, and UnityEvent "
            "connections before making assumptions about the scene. The graph "
            "auto-reloads when the project is rebuilt, so you always see the "
            "latest state."
        ),
    )

    @server.tool(description="List all components attached to a GameObject by name.")
    def get_components(gameobject_name: str) -> dict[str, Any]:
        return gtools.get_components(graph_ref.current(), gameobject_name)

    @server.tool(
        description=(
            "Return Inspector-set field values for a component on a GameObject. "
            "For scripts, also returns code defaults and flags any overrides -- "
            "critical for distinguishing Inspector-tuned values from code literals."
        )
    )
    def get_inspector_values(component_name: str, gameobject_name: str) -> dict[str, Any]:
        return gtools.get_inspector_values(graph_ref.current(), component_name, gameobject_name)

    @server.tool(description="Get the full GameObject list for a scene by name.")
    def get_scene_graph(scene_name: str) -> dict[str, Any]:
        return gtools.get_scene_graph(graph_ref.current(), scene_name)

    @server.tool(description="Find all GameObjects that have a given script attached.")
    def find_script_usages(script_name: str) -> dict[str, Any]:
        return gtools.find_script_usages(graph_ref.current(), script_name)

    @server.tool(
        description=(
            "List UnityEvent connections for a GameObject -- both outgoing (events this "
            "object fires) and incoming (callbacks listening on this object)."
        )
    )
    def get_event_connections(gameobject_name: str) -> dict[str, Any]:
        return gtools.get_event_connections(graph_ref.current(), gameobject_name)

    @server.tool(
        description=(
            "Return the prefab variant inheritance chain. Reports each step from the "
            "given prefab up to the base, plus any recorded field overrides."
        )
    )
    def get_prefab_chain(prefab_name: str) -> dict[str, Any]:
        return gtools.get_prefab_chain(graph_ref.current(), prefab_name)

    @server.tool(
        description=(
            "BFS N-hop neighborhood around a node id or name. Use this to see "
            "everything within 1-3 hops of a given entity."
        )
    )
    def get_neighbors(node_id: str, hops: int = 1) -> dict[str, Any]:
        return gtools.get_neighbors(graph_ref.current(), node_id, hops)

    @server.tool(
        description=(
            "Shortest path between two nodes (ids or names). Returns the node "
            "sequence and the edge types traversed."
        )
    )
    def shortest_path(from_id: str, to_id: str) -> dict[str, Any]:
        return gtools.shortest_path(graph_ref.current(), from_id, to_id)

    @server.tool(
        description=(
            "Simple natural-language graph query -- extracts entity tokens from "
            "the text, finds matching nodes, returns their 2-hop subgraph. "
            "For token-budgeted retrieval (Layer 2), use inject_context instead."
        )
    )
    def query_graph(natural_language_query: str, max_nodes: int = 50) -> dict[str, Any]:
        return gtools.query_graph(graph_ref.current(), natural_language_query, max_nodes)

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
            graph_ref.current(),
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

    # ── v1.6.0 deterministic query library ──────────────────────────────
    @server.tool(
        description=(
            "Every inbound reference to a script -- attachments, GetComponent/"
            "FindObjectOfType/method callers, subclasses, UnityEvent listeners. "
            "Each usage includes evidence sites (file:line)."
        )
    )
    def who_uses(script_name: str) -> dict[str, Any]:
        return gqueries.who_uses(graph_ref.current(), script_name)

    @server.tool(
        description=(
            "Blast radius -- every node reachable outbound from this script "
            "within `hops`. Reports the first edge type that reached each "
            "target, so you can gauge what a refactor touches."
        )
    )
    def impact_of(script_name: str, hops: int = 2) -> dict[str, Any]:
        return gqueries.impact_of(graph_ref.current(), script_name, hops=hops)

    @server.tool(
        description=(
            "Scripts attached to `min_attachments` or more GameObjects across "
            "the project. These are 'used everywhere' -- renames and API "
            "changes have outsize blast radius. `user_only` (default true) "
            "drops Unity built-ins, third-party asset packs, and unresolved "
            "placeholders; set false to see everything."
        )
    )
    def find_singletons(min_attachments: int = 2, user_only: bool = True) -> dict[str, Any]:
        return gqueries.find_singletons(
            graph_ref.current(),
            min_attachments=min_attachments,
            user_only=user_only,
        )

    @server.tool(
        description=(
            "All Inspector-tuned fields for a script across every scene/prefab "
            "attachment. An override means the scene value differs from the "
            "code-level default -- the field where Claude Code is most often "
            "wrong by reading .cs alone."
        )
    )
    def inspector_overrides_for(script_name: str) -> dict[str, Any]:
        return gqueries.inspector_overrides_for(graph_ref.current(), script_name)

    @server.tool(
        description=(
            "Every place `script_name.field_name` is wired in scenes/prefabs "
            "as a UnityEvent listener. Call before renaming a serialized "
            "UnityEvent field."
        )
    )
    def field_wiring(script_name: str, field_name: str) -> dict[str, Any]:
        return gqueries.field_wiring(graph_ref.current(), script_name, field_name)

    @server.tool(
        description=(
            "All UnityEvent callbacks that land on methods of a script. Run "
            "before renaming a public method -- UnityEvent strings bind by "
            "name, not by reference."
        )
    )
    def event_listeners(script_name: str) -> dict[str, Any]:
        return gqueries.event_listeners(graph_ref.current(), script_name)

    @server.tool(
        description=(
            "Placeholder Script nodes -- scene/prefab references to a "
            "script_guid that doesn't resolve to a .cs file in this project. "
            "Usually indicates a deleted script, a renamed class, or a "
            "stripped package. `min_attachments` (default 1) filters out "
            "placeholders with no live references."
        )
    )
    def find_missing_scripts(min_attachments: int = 1) -> dict[str, Any]:
        return gqueries.find_missing_scripts(
            graph_ref.current(), min_attachments=min_attachments
        )

    return server


def run_stdio_server(graph_path: Path) -> None:
    server = build_server(graph_path)
    server.run(transport="stdio")
