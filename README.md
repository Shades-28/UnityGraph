# UnityGraph

**Claude Code for Unity, without the scene-context gap.**

Claude Code can read your C# source, but it can't open your Unity scene.
It doesn't know what components are on the `Player` GameObject, what
Inspector value you set for `_speed`, or which button fires
`OnAttackPressed`. All of that lives in Unity's YAML — invisible to
source-only context. UnityGraph fixes it.

Point UnityGraph at your Unity project, run two commands, and every Claude
Code session in that folder gets:

- A **knowledge graph** of scenes, prefabs, scripts, Animators, and
  ShaderGraphs, with Inspector values attached where they matter.
- An **MCP server** exposing 10 query tools Claude invokes on demand.
- An **injection engine** that, given a task, selects the relevant
  subgraph and emits a token-budgeted UNITYGRAPH CONTEXT block.
- A **behavior model** that learns which failure patterns Claude
  actually hits on your project and adapts the retrieval accordingly.

No Unity Editor required. Installs in seconds. All three layers run
locally.

---

## Install

```bash
pip install "unitygraph[full]"   # includes Layer 2 (inject) + Layer 3 (behavior)
cd /path/to/your/unity/project
unitygraph init .                # scaffolds CLAUDE.md, .mcp.json, .claude/skills/unity-aware/
unitygraph build .               # parses Assets/ -> graph-out/graph.json
```

Next Claude Code session in this folder picks up the MCP server
automatically.

**Minimal install (Layer 1 only):** `pip install unitygraph` gives you the
graph + MCP server without the inject/behavior extras.

---

## Update

When a newer UnityGraph is released, or you've pulled a newer version of the
editable install, refresh your projects with one command:

```bash
cd /path/to/your/unity/project
unitygraph update .
```

This:

- Syncs every template file (`CLAUDE.md`, `.mcp.json`, `.claude/settings.json`,
  `.claude/skills/unity-aware/SKILL.md`) to the installed version.
- Preserves files you've hand-edited — anything with a `TODO` / `# custom`
  marker is left alone and flagged as `custom`.
- Rebuilds the graph via `build . --update` (incremental; reuses the parse
  cache).

Useful flags:

```bash
unitygraph update . --check           # preview changes without writing
unitygraph update . --templates-only  # refresh templates, skip graph rebuild
unitygraph update . --graph-only      # rebuild graph, skip template sync
```

To update the `unitygraph` package itself:

```bash
pip install -U "unitygraph[full]"     # published PyPI version
# or, for the editable local install:
cd /path/to/UnityGraph
git pull
pip install -e ".[full]"              # re-installs if dependencies changed
```

Then in every Unity project that uses it: `unitygraph update .`

---

## The three layers

| Layer | Role | Ships as |
|---|---|---|
| **L1 — Knowledge Graph** | Parses `.cs`/`.unity`/`.prefab`/`.controller`/`.shadergraph` into a single `graph.json`. 9 MCP query tools (`get_components`, `get_inspector_values`, `get_event_connections`, `get_prefab_chain`, …). | MIT open source |
| **L2 — Injection Engine** | Picks task-relevant subgraph + formats it as a 1,500-token context block. Entity-hop / task-type / full-neighborhood strategies. 10th MCP tool: `inject_context`. | Commercial license |
| **L3 — Behavior Model** | Observes every inject call, records feedback, learns which failure patterns fire on this project, adapts Layer 2 retrieval to close the gap. | Commercial premium |

See [`UnityGraph_Project_Spec.md`](UnityGraph_Project_Spec.md) for the full
specification and [`UnityGraph_Development_Plan.md`](UnityGraph_Development_Plan.md)
for the iteration-by-iteration build history.

---

## Observatory — live reactive visualization

```bash
unitygraph viz .
```

Opens your browser to a dark-themed, force-directed "galaxy" view of the
project graph. Every time the graph rebuilds (Stop hook, manual `build
--update`, anything else), the page animates the new nodes in without a
refresh — search, filter by node type, click for a detail card showing
Inspector values, script fields, prefab chains, etc.

Type-colored constellations: Scripts (ember), GameObjects (cold cyan),
Components (mercury), Scenes (plum), Prefabs (sea-foam),
AnimatorControllers (rose gold), AnimStates (lilac), ShaderGraphs (coral).

## CLI reference

```
unitygraph build <path> [-o OUT] [--update] [-v]
unitygraph serve <graph.json>                     # MCP stdio server
unitygraph viz   [graph.json] [--project DIR] [--port N] [--no-browser]
unitygraph init  [path] [--force] [--no-skill]    # scaffold Claude integration
unitygraph update [path] [--check] [--templates-only] [--graph-only]
unitygraph inject "<task>" --graph graph.json     # dump a UNITYGRAPH CONTEXT block
unitygraph feedback correct|incorrect [--session ID] [--note TXT]
unitygraph patterns list|show|promote|stats|replay
```

---

## Example: the headline bug

In a Unity project:

```csharp
[SerializeField] private float _speed = 5.0f;   // code default

private void HandleDamaged(int amount) {
    _speedMultiplier = Mathf.Max(0.1f, 1.0f - (amount / 5.0f));  // wrong!
}
```

The Inspector on the `Player` GameObject sets `_speed = 7.0` — the
hardcoded `5.0f` in `HandleDamaged` is a baseline-blind mistake. Without
scene data, Claude reads the code default, concludes the math is fine, and
preserves the bug.

With UnityGraph, Claude calls `get_inspector_values("PlayerController",
"Player")`, sees `_speed = 7.0 (code default: 5.0f)`, and produces the
right fix:

```diff
- _speedMultiplier = Mathf.Max(0.1f, 1.0f - (amount / 5.0f));
+ _speedMultiplier = Mathf.Max(0.1f, 1.0f - (amount / _speed));
```

This is the I1 headline test; transcript checked in at
[`evals/i1_headline/`](evals/i1_headline/).

---

## Benchmark

**UnityBench** measures the scene-context gap empirically. 19 hand-authored
tasks × 3 conditions × 5 metrics:

| Condition | What Claude sees |
|---|---|
| `baseline` | task text + source file |
| `manual_visual` | + human-authored scene description |
| `unitygraph` | + Layer 2 context block |
| `unitygraph_adaptive` | + Layer 3 pattern-matched adaptation |

```bash
export ANTHROPIC_API_KEY=sk-...
python -m evals.unitybench.runner
python -m evals.unitybench.report
```

Scope-scale note: paper-grade version is 120 tasks + Unity Test Runner
integration. The MVP harness is runnable today.

---

## Research

Three papers fall out of the three layers. See `papers/` for
supplementary-material stubs:

- **L1** — *What minimal graph schema captures Unity-specific semantics?*
  Schema comparison across 10+ projects. → MSR / FSE
- **L2** — *Automated graph injection closes the scene-code gap.*
  UnityBench + 3 conditions. → ASE / ICSE
- **L3** — *External behavioral model of LLM domain priors outperforms
  static injection.* → ICSE / NeurIPS

---

## Status

- L1 v0.1.0 — complete. 9 MCP tools, 5 parser types, 3 real Unity projects
  validated (Indian-Bike-Gangster-3D, clash.io, Graudation-Saga at 72k nodes).
- L2 v0.2.0 — complete. 3 strategies, token budget, 10th MCP tool, skill
  manifest. Real-API benchmark awaits `ANTHROPIC_API_KEY`.
- L3 v0.4.0 — complete. Observation loop, 6-pre-seed pattern map,
  adaptive injection matcher. Pattern auto-promotion gate validated end-to-end.
- v1.0.0 — this release. Bundle install, unified CLI, papers scaffold.

96 tests pass, ruff + mypy strict clean, 3 real Unity projects survived.

---

## License

- **Layer 1** (parsers, graph model, MCP server, 9 tools) — **MIT**.
- **Layer 2** (inject engine, skill, `inject_context` tool) — commercial
  license (details in `LICENSE-COMMERCIAL.md` once published).
- **Layer 3** (observation, pattern map, adaptive matcher) — premium
  commercial.
- Bundle license covers all three + UnityBench dataset + commercial use
  rights.

Contact RinvalAI for commercial licensing terms.
