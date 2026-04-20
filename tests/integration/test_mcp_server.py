"""Integration tests — spawn the real MCP stdio server and call each tool.

Uses the MCP client SDK to drive the server the same way Claude Code will.
Verifies the full pipeline: CLI build → graph.json → MCP server → tool call
→ structured response.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from unitygraph.build.builder import build_project

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject"


@pytest.fixture(scope="module")
def graph_path(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("graph")
    result = build_project(FIXTURE)
    out_path = out_dir / "graph.json"
    result.graph.write(out_path)
    return out_path


async def _run_mcp(graph_path: Path):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "unitygraph.serve", str(graph_path)],
        env=None,
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        tool_names = {t.name for t in tools.tools}

        get_components = await session.call_tool("get_components", {"gameobject_name": "Player"})
        get_inspector = await session.call_tool(
            "get_inspector_values",
            {"component_name": "PlayerController", "gameobject_name": "Player"},
        )
        get_scene = await session.call_tool("get_scene_graph", {"scene_name": "Main"})
        find_usages = await session.call_tool("find_script_usages", {"script_name": "EnemyAI"})
        get_events = await session.call_tool(
            "get_event_connections", {"gameobject_name": "UI_Button"}
        )
        return {
            "tool_names": tool_names,
            "get_components": get_components,
            "get_inspector": get_inspector,
            "get_scene": get_scene,
            "find_usages": find_usages,
            "get_events": get_events,
        }


def _payload(result):
    """FastMCP returns structured data on call_tool results as structuredContent or JSON text."""
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
    return None


def test_mcp_server_all_five_tools(graph_path):
    results = asyncio.run(_run_mcp(graph_path))

    expected_tools = {
        "get_components",
        "get_inspector_values",
        "get_scene_graph",
        "find_script_usages",
        "get_event_connections",
    }
    assert expected_tools.issubset(results["tool_names"]), (
        f"missing tools: {expected_tools - results['tool_names']}"
    )

    gc = _payload(results["get_components"])
    assert gc is not None
    assert gc["matches"]
    assert "PlayerController" in gc["matches"][0]["scripts"]

    gi = _payload(results["get_inspector"])
    assert gi is not None
    assert gi["found"] is True
    assert gi["matches"][0]["inspector_values"]["_speed"] == 7.0
    overrides = {o["field"] for o in gi["matches"][0]["overrides"]}
    assert "_speed" in overrides

    gs = _payload(results["get_scene"])
    assert gs is not None
    assert gs["found"] is True
    assert gs["count"] == 5

    fu = _payload(results["find_usages"])
    assert fu is not None
    assert fu["count"] == 2

    ge = _payload(results["get_events"])
    assert ge is not None
    assert ge["outgoing"]
    assert any(e.get("method") == "OnAttackPressed" for e in ge["outgoing"])
