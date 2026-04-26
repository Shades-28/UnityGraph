"""Fresh-user dry-run: launch the MCP server the way Claude Code does
and verify a few tool calls return sensible results on a real project.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    project = Path(os.environ.get("UNITYGRAPH_DRY_RUN_PROJECT", "D:/PR/Unity/my-supermarket"))
    graph_path = project / "graph-out" / "graph.json"
    if not graph_path.exists():
        print(f"ERROR: no graph at {graph_path}. Run 'unitygraph build .' first.", file=sys.stderr)
        sys.exit(1)

    # Launch the server exactly the way Claude Code would per .mcp.json.
    params = StdioServerParameters(
        command="unitygraph",
        args=["serve", str(graph_path)],
        env=None,
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        print(f"server reports {len(tools.tools)} tools")

        # Smoke-test a few queries that don't depend on knowing the project.
        queries = [
            ("find_missing_scripts", {"min_attachments": 5}),
            ("find_singletons", {"min_attachments": 3}),
        ]
        for name, args in queries:
            print(f"\n=== {name}({args}) ===")
            result = await session.call_tool(name, args)
            for block in result.content:
                text = getattr(block, "text", None)
                if text:
                    parsed = json.loads(text)
                    if "count" in parsed:
                        print(f"  count: {parsed['count']}")
                    elif "singletons" in parsed:
                        for s in parsed["singletons"][:3]:
                            print(f"  - {s['script']['name']}: {s['attachment_count']} attachments")
                    else:
                        print(f"  keys: {list(parsed.keys())[:5]}")
                    break


if __name__ == "__main__":
    asyncio.run(main())
