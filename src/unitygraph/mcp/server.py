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

    return server


def run_stdio_server(graph_path: Path) -> None:
    server = build_server(graph_path)
    server.run(transport="stdio")
