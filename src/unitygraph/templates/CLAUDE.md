## UnityGraph Knowledge System

This project has a live knowledge graph at `graph-out/graph.json` and an MCP
server that exposes it (see `.mcp.json`).

**BEFORE answering any question about this project:**

1. Call `get_components` for any GameObject mentioned in the task -- see what
   else lives on that object.
2. Call `get_inspector_values` for components you plan to modify -- Inspector
   values override code defaults. The `overrides` field tells you which
   fields were tuned in the Inspector.
3. Call `get_event_connections` if the task involves UI, triggers, or events --
   UnityEvent wiring is stored in scene YAML, not in code.
4. Call `find_script_usages` before refactoring a script -- the same script
   can be attached across multiple scenes and prefabs.
5. Call `get_scene_graph` when you need to reason about the full set of
   GameObjects in a scene.

**Rules:**

- Never assume a script's runtime behavior from code alone. Inspector values
  can override any `[SerializeField]`.
- The graph is ground truth for scene structure. Code is ground truth for
  logic. Use both.
- If a tool returns `found: false` for something the task mentions, state
  that to the user before proceeding -- the graph is stale or the name is
  wrong.

**When the graph is stale:** rebuild with `unitygraph build .`. The build is
incremental once `--update` ships (planned Iteration 3).
