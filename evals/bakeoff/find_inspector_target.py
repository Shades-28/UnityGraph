"""Find a clash.io script with concrete (scalar) Inspector overrides
where code default and scene value differ on a primitive.
"""
import os
from pathlib import Path

from unitygraph.build.graph import Graph
from unitygraph.mcp import queries

EVAL_ROOT = Path(os.environ.get("UNITYGRAPH_EVAL_ROOT", "D:/PR/Unity"))
GRAPH = Graph.load(EVAL_ROOT / "clash.io" / "graph-out" / "graph.json")


def main() -> None:
    for n in GRAPH.nodes:
        if n.type != "Script":
            continue
        fp = str(n.data.get("file_path", "")).replace("\\", "/")
        if "_Assets/Scripts" not in fp:
            continue
        result = queries.inspector_overrides_for(GRAPH, n.data["name"])
        if not result.get("found"):
            continue
        scalar_overrides = []
        for att in result.get("attachments", []):
            for ov in att["overrides"]:
                # Filter: scalar default, scalar value, both not None
                if isinstance(ov["code_default"], (int, float, str, bool)) and isinstance(
                    ov["inspector_value"], (int, float, str, bool)
                ):
                    scalar_overrides.append((att["gameobject"].get("name"), ov))
        if scalar_overrides:
            print(f"== {n.data['name']} ({n.data['file_path']}) ==")
            for go, ov in scalar_overrides:
                print(f"  {go}.{ov['field']} = {ov['inspector_value']}  (default {ov['code_default']})")


if __name__ == "__main__":
    main()
