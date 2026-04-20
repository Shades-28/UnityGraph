---
name: unity-aware
description: Use when working in a Unity C# project that has UnityGraph installed (detect via the presence of `graph-out/graph.json` or `.mcp.json` referencing unitygraph). Gives Claude first-class access to scene GameObjects, Inspector-overridden values, UnityEvent connections, prefab variant chains, Animator states, and ShaderGraph inputs through an MCP server. Eliminates the scene-code gap so Claude can answer "what components live on X", "what Inspector values are set on Y", "who listens to Z's onClick" without screenshots or manual context.
---

# Unity-Aware Skill

This skill activates when editing a Unity project instrumented with
[UnityGraph](https://github.com/rinvalai/unitygraph). UnityGraph's MCP server
exposes 10 tools that let you query scene structure, Inspector values,
UnityEvent wiring, and prefab chains — all of which Unity YAML hides from
source-only context.

## When to use which tool

| Situation | First tool to call |
|---|---|
| User mentions a specific GameObject by name | `get_components(gameobject_name)` |
| Task modifies a `[SerializeField]` field or asks about its runtime value | `get_inspector_values(component_name, gameobject_name)` |
| Task involves UI buttons, triggers, or cross-object events | `get_event_connections(gameobject_name)` |
| Refactoring a script — need to find every usage | `find_script_usages(script_name)` |
| Need the full list of objects in a scene | `get_scene_graph(scene_name)` |
| Working with a prefab that may be a variant | `get_prefab_chain(prefab_name)` |
| Exploring around a known entity (e.g. "everything near Player") | `get_neighbors(node_id_or_name, hops)` |
| Reasoning about multi-hop dependencies | `shortest_path(from, to)` |
| Prose task with no clear entity yet | `query_graph(natural_language_query)` |
| Want a pre-formatted context block for a task | `inject_context(task_text, budget=1500)` |

## Rules

1. **Inspector values override code defaults.** Before modifying a
   `[SerializeField]` field's semantics, call `get_inspector_values` to see
   what the scene/prefab actually configures. A numeric comment in the code
   is often wrong at runtime.
2. **UnityEvent wiring is invisible in source.** If a public method has no
   callers in the C# files but the task references a button or trigger,
   check `get_event_connections` — the scene YAML almost certainly wires
   it up.
3. **Prefab variants silently override.** Before reporting a prefab's
   field value, call `get_prefab_chain` — a scene instance may override
   what the base prefab sets.
4. **`get_neighbors` is cheap.** When unsure of scope, pull 2-hop
   neighborhoods and let the structure inform your plan.
5. **Prefer `inject_context` for full-task reasoning.** When a task is
   ambiguous or involves many objects, `inject_context` produces a
   token-budgeted block with the highest-signal nodes preselected.

## Confidence reading

`inject_context` and the ad-hoc tools all carry scene data with
varying completeness. Treat the `confidence` field as follows:

- `HIGH` — every referenced script has Inspector data on its attachment
  edge. Trust the values.
- `MEDIUM` — some scripts are attached but missing Inspector overrides
  (often on scenes that use code defaults). Double-check if the task
  is about specific numeric values.
- `LOW` — the retrieval didn't find scene attachments. The response is
  code-only context; note this explicitly if the task would benefit
  from scene awareness.

## Not for

- Pure-shader graph-programming tasks. The graph only captures
  input/output/keyword surface, not node connectivity.
- Animator state transitions involving BlendTree internals. States +
  transitions are parsed; BlendTree children are not.
- Addressables / AssetBundle loading patterns. Graph only covers
  in-project assets, not runtime loading.
