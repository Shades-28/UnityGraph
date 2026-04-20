# UnityGraph Layer 2 — Unity-Aware Claude Code

**Give Claude Code the scene context it's missing.**

Claude Code can read your C# source, but it can't open your Unity scene. It
doesn't know what components are on the `Player` GameObject, what Inspector
value you set for `_speed`, or which button fires `OnAttackPressed`. All of
that lives in Unity's YAML, which Claude never sees.

Layer 2 fixes this. Point UnityGraph at your Unity project, run `unitygraph
init`, and every Claude Code session in that folder gets:

- A **knowledge graph** of your scenes, prefabs, scripts, Animators, and
  ShaderGraphs, with Inspector values attached where they matter.
- An **MCP server** that exposes 10 query tools Claude calls on demand.
- A **skill** (`unity-aware`) that tells Claude when and how to reach for
  those tools.
- An **injection engine** that, given a task prompt, selects the relevant
  subgraph and emits a token-budgeted context block that goes into Claude's
  prompt automatically.

## Install

```bash
pip install unitygraph
cd /path/to/your/unity/project
unitygraph init .          # writes CLAUDE.md, .mcp.json, .claude/skills/unity-aware/
unitygraph build .         # emits graph-out/graph.json
```

The next `claude` session started in this folder will pick up the MCP
server automatically. No Unity Editor required at any step.

## What changed vs Layer 1

| | Layer 1 (v0.1.0) | Layer 2 (v0.2.0) |
|---|---|---|
| MCP tools | 9 | 10 (adds `inject_context`) |
| Retrieval strategies | — | entity_hop / task_type / full_neighborhood |
| Context formatting | — | UNITYGRAPH CONTEXT block with Inspector vs code-default rows |
| Token budget | — | default 1500, configurable per call |
| Confidence scoring | — | HIGH / MEDIUM / LOW on every block |
| Skill packaging | — | `.claude/skills/unity-aware/SKILL.md` installed by `init` |
| In-process cache | — | LRU on `(task, graph_id, strategy, budget)` |

## Benchmark

UnityBench: 19 hand-authored Unity coding tasks (6 isolated-script, 10
cross-artifact, 3 full-project) evaluated across three conditions:

| Condition | What Claude sees |
|---|---|
| baseline | task text + source file |
| manual_visual | + developer-written scene description |
| unitygraph | + Layer 2's `inject_context` block |

Run it yourself:

```bash
export ANTHROPIC_API_KEY=sk-...
python -m evals.unitybench.runner
python -m evals.unitybench.report
```

The runner prompt-caches the system prompt, so a full 57-trial sweep on
Sonnet 4.6 costs ~$2-5 end-to-end. The report flags the Iteration 5 gate
(≥30% relative Tier-2 improvement) PASS/FAIL automatically.

Scope-scaling note: the paper-grade benchmark targets 120 tasks with Unity
Test Runner batch-mode scoring. This package ships the MVP harness and 19
tasks; the full scale-up is additive (no code changes, just more tasks).

## Using `inject_context` inside Claude Code

If you're comfortable writing MCP tool calls in a session:

```
> inject_context(task_text="fix the slow on PlayerController", budget=1500)
```

Returns `block`, `strategy`, `confidence`, `token_count`, and the seed
nodes the retrieval started from. Drop `block` straight into your working
context.

For most users the `unity-aware` skill takes care of this automatically:
Claude notices the task names a specific GameObject / script, calls the
right lookup tool, and works from the result.

## Query tool reference

All 10 tools live on the `unitygraph` MCP server. Full docs in
`src/unitygraph/mcp/server.py`; quick summary:

| Tool | Use when |
|---|---|
| `get_components(name)` | Listing components on a GameObject |
| `get_inspector_values(component, gameobject)` | Checking Inspector overrides vs code defaults |
| `get_scene_graph(scene_name)` | Full GameObject list for a scene |
| `find_script_usages(script_name)` | Every scene/prefab that has this script |
| `get_event_connections(gameobject_name)` | UnityEvent wiring (onClick, etc.) |
| `get_prefab_chain(prefab_name)` | Variant inheritance + overrides |
| `get_neighbors(node_id, hops)` | N-hop BFS around any node |
| `shortest_path(from, to)` | Path + edge types between two entities |
| `query_graph(text)` | Minimal prose-to-subgraph shortcut |
| `inject_context(task_text)` | Full token-budgeted context block |

## Limitations

- ShaderGraph parsing covers the input/output/keyword surface only, not
  node-level connectivity.
- Animator BlendTree children are not expanded beyond the state's motion
  guid.
- Addressables / AssetBundle runtime loading isn't modeled (the graph is
  asset-time, not runtime).

These land in later iterations (see `UnityGraph_Development_Plan.md`).

## License

Layer 1 (parsers, graph model, MCP server, 9 tools) is MIT. Layer 2
(inject engine, skill, `inject_context`) ships under a separate commercial
license once released publicly — for now it's internal.
