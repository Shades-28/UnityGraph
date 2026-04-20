"""MCP server entry point — ``python -m unitygraph.serve <graph.json>``.

Matches the ``.mcp.json`` launch command referenced in the project spec
(``args: ["-m", "unitygraph.serve", "graph-out/graph.json"]``).
"""

from __future__ import annotations

import sys
from pathlib import Path

from unitygraph.mcp.server import run_stdio_server


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m unitygraph.serve <graph.json>", file=sys.stderr)
        return 2
    graph_path = Path(sys.argv[1]).resolve()
    if not graph_path.exists():
        print(f"graph not found: {graph_path}", file=sys.stderr)
        return 2
    run_stdio_server(graph_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
