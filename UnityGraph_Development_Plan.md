# UnityGraph — Complete Development Plan

**Owner:** autonomous execution (Claude Code as senior engineer)
**Version:** 1.0 — 2026-04-21
**Companion to:** `UnityGraph_Project_Spec.md`

This plan turns the three-layer spec into a concrete, iterative build. Each iteration ships a working artifact. No layer starts until the layer below has passed its validation gate. Written as if I am the one executing it end-to-end with full autonomy.

---

## 0. Guiding principles for execution

1. **Ship thin vertical slices, not horizontal layers.** The first useful artifact is "Claude solves one real Unity bug via MCP." Everything in Iteration 1 drives toward that. No broader scope until that works.
2. **Musk-algorithm applied to every iteration.** Before writing code for a feature: question the requirement, delete what I can, simplify, accelerate loop, automate last.
3. **Validation gates are non-negotiable.** An iteration is done when its gate passes on a real fixture project, not when the code compiles.
4. **One fixture project, checked in.** `fixtures/MiniUnityProject/` — 1 scene, ~5 GameObjects, 3 scripts, 1 prefab, 1 UnityEvent connection. Every parser test runs against it. It is the canary.
5. **Claude designs internals; spec defines contract.** Schemas, class layouts, module boundaries are my call. External contracts (graph.json shape v1, MCP tool signatures, CLI flags) are frozen once published.
6. **Commit discipline:** every iteration is one branch, merged behind a passing gate. No long-lived feature branches.

---

## 1. Repository layout (decided upfront, frozen)

```
UnityGraph/
├── UnityGraph_Project_Spec.md          # the what
├── UnityGraph_Development_Plan.md      # this file
├── README.md                           # install + quickstart (written at I1 close)
├── pyproject.toml                      # single package: unitygraph
├── src/unitygraph/
│   ├── __init__.py
│   ├── cli.py                          # `unitygraph` entry point
│   ├── serve.py                        # MCP server entry point
│   ├── build/                          # parsing + graph construction (L1)
│   │   ├── parsers/
│   │   │   ├── cs_parser.py
│   │   │   ├── scene_parser.py
│   │   │   ├── prefab_parser.py
│   │   │   ├── execorder_parser.py
│   │   │   ├── animator_parser.py       # added in I3
│   │   │   └── shadergraph_parser.py    # added in I3
│   │   ├── graph.py                    # node/edge model + serialization
│   │   └── builder.py                  # orchestrates parsers -> graph.json
│   ├── mcp/                            # MCP server + tool handlers (L1)
│   │   ├── server.py
│   │   └── tools.py
│   ├── inject/                         # L2
│   │   ├── entities.py
│   │   ├── retrieval.py
│   │   ├── formatter.py
│   │   └── budget.py
│   ├── behavior/                       # L3
│   │   ├── observer.py
│   │   ├── patterns.py
│   │   └── feedback.py
│   └── schemas/                        # JSON schemas for graph.json, patterns, etc.
├── fixtures/
│   ├── MiniUnityProject/               # tiny fixture used throughout
│   └── UnityBench/                     # built in I5
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── evals/                              # UnityBench runner (I5+)
└── .github/workflows/ci.yml
```

**Frozen at I1:** package name, CLI name, MCP tool names, `graph.json` v1 top-level shape.
**Fluid:** everything inside modules.

---

## 2. External contracts (frozen at I1 close)

### 2.1 `graph.json` v1 top-level shape

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-04-21T12:00:00Z",
  "project_root": "/abs/path",
  "stats": { "n_nodes": 0, "n_edges": 0, "build_ms": 0 },
  "nodes": [ { "id": "...", "type": "...", "...": "..." } ],
  "edges": [ { "from": "...", "to": "...", "type": "...", "...": "..." } ]
}
```

Node/edge field names are Claude's call at implementation time, but `id`, `type`, `from`, `to` are frozen. New node/edge types are additive.

### 2.2 MCP tools (names + signatures frozen)

v0 (I1): `get_components`, `get_inspector_values`, `get_scene_graph`, `find_script_usages`, `get_event_connections`
v1 (I3): + `get_prefab_chain`, `get_neighbors`, `shortest_path`, `query_graph`

### 2.3 CLI

v0 (I1): `unitygraph build <path> [--output DIR]`, `unitygraph serve <graph.json>`
v1 (I3): + `unitygraph build --update`

---

## 3. Iteration plan

Each iteration has: **goal, scope, deliverables, validation gate, exit criterion**. I do not move on until the gate passes.

### Iteration 0 — Bootstrap (0.5 week)

**Goal:** repo runnable, CI green, fixture project committed.

**Scope:**
- `pyproject.toml` with `unitygraph` package, entry points for `unitygraph` CLI and `unitygraph.serve`
- Dev deps: `pytest`, `ruff`, `mypy`, `tree-sitter`, `tree-sitter-c-sharp`, `PyYAML`, `mcp` (the Anthropic MCP Python SDK)
- `fixtures/MiniUnityProject/`: hand-authored minimal Unity project
  - `Assets/Scenes/Main.unity` with Player, Enemy, UI_Button, Camera, Ground
  - `Assets/Scripts/PlayerController.cs`, `HealthSystem.cs`, `EnemyAI.cs`
  - `Assets/Prefabs/Enemy.prefab` (not a variant yet)
  - One UnityEvent: `UI_Button.onClick` → `PlayerController.OnAttackPressed`
  - One Inspector override: `PlayerController._speed = 7.0` (code default 5.0)
  - `ProjectSettings/ScriptExecutionOrder.asset` forcing `HealthSystem` before `PlayerController`
- GitHub Actions: lint + typecheck + unit tests on push
- `unitygraph --version` works

**Gate:** CI passes on empty test; `python -m unitygraph.cli --help` prints usage.

---

### Iteration 1 — L1 vertical slice: one real bug, end-to-end (2 weeks)

**Goal:** Claude Code, connected to the MCP server, correctly fixes one concrete Unity bug in `MiniUnityProject` that it fails on without the graph.

This is the entire point of L1. Everything in I1 exists to make this happen.

**The target bug (chosen now, frozen):**
> In `MiniUnityProject`, `PlayerController._speed` is set to `7.0` in the Inspector but the code default is `5.0`. The `HealthSystem.OnTakeDamage` applies a slow that assumes max speed is 5.0, so damage feels wrong. Task given to Claude: *"Make the slow effect proportional to actual player speed."*
>
> Without the graph: Claude reads `_speed = 5.0` from code, produces wrong math.
> With the graph: Claude calls `get_inspector_values("PlayerController", "Player")`, sees `_speed = 7.0`, produces correct math.

**Scope (Musk-cut from spec §1):**
- **Parsers:**
  - `cs_parser.py` — tree-sitter. Extracts: class name, base class, `[SerializeField]` fields (name + type + default literal), public fields, method names, MonoBehaviour lifecycle method presence, `GetComponent<T>` calls
  - `scene_parser.py` — PyYAML with Unity tag hack. Extracts: GameObject names + fileID, component list per GO (resolved via fileID→MonoScript guid lookup), Inspector field values, parent-child hierarchy, tag, layer, active state
  - `prefab_parser.py` — same as scene, flat (no variant chains yet)
  - `execorder_parser.py` — simple YAML read of `ScriptExecutionOrder.asset`
- **Graph:** `nodes[]` + `edges[]`. Node types: `Script`, `GameObject`, `Component`, `Scene`, `Prefab`. Edge types: `attached_to`, `co_exists_with`, `depends_on` (GetComponent), `inherits`, `subscribes_to` (UnityEvent), `loads_scene` (if any).
- **Builder:** walks project, runs parsers, emits `graph.json` to `graph-out/graph.json`.
- **MCP server:** stdio, 5 tools from §2.2 v0. In-memory graph load on startup.
- **CLI:** `build` + `serve` only.
- **Integration test harness:** a test that spawns the MCP server, calls each of the 5 tools against fixture output, asserts expected JSON.

**Explicitly deferred to I3:** ShaderGraph, Animator Controller, prefab variants/`is_variant_of`/`overrides`, incremental `--update`, `shortest_path`/`get_neighbors`/`query_graph`, CLI `query` subcommand.

**Gate (all must pass):**
1. `unitygraph build fixtures/MiniUnityProject` produces `graph.json` in <5s with zero errors
2. Graph contains: Player GameObject node with edges to PlayerController, HealthSystem, Rigidbody, Collider; `attached_to` + `co_exists_with` edges present; `_speed = 7.0` stored on the PlayerController component node
3. `unitygraph serve graph.json` starts, all 5 MCP tools respond with correct JSON for the fixture
4. **The headline test:** in a real Claude Code session with `.mcp.json` pointing at the fixture's `graph.json`, given the target bug's task text, Claude calls `get_inspector_values`, receives `7.0`, and writes code that uses the runtime speed value (not the hardcoded 5.0). Recorded as a transcript checked into `evals/i1_headline.transcript.md`.
5. Unit test coverage ≥70% on parsers; integration tests green in CI

**Exit criterion:** gate 4 recorded and reviewable.

---

### Iteration 2 — L1 robustness + 3 more Unity projects (1.5 weeks)

**Goal:** L1 works on real, non-toy Unity projects. Build time success criterion met.

**Scope:**
- Pull 3 public Unity sample projects (e.g., Unity's own *2D Platformer Microgame*, *Karting Microgame*, and one open-source community project). Committed as git submodules or referenced paths.
- Fix every crash/malformed-YAML/edge case surfaced by these projects. The spec explicitly calls out "error handling and partial-parse recovery when Unity YAML is malformed" — this is where that work happens, not I1.
- Add structured logging (`--verbose` flag) for parse failures — emit a warning, skip the file, continue.
- Performance: ensure <60s build on the largest of the 3 (spec §1.9).
- Expand fixture MCP integration tests to cover all 3 projects.

**Gate:**
1. `unitygraph build` succeeds on all 3 external projects with <5% files skipped due to parse errors
2. Build time <60s on the largest project (spec requirement)
3. All 5 MCP tools respond in <500ms on the largest graph
4. No regressions on `MiniUnityProject` headline test

**Exit criterion:** the three external graphs are committed to `evals/graphs/` for reuse in L2.

---

### Iteration 3 — L1 v1 completeness (1.5 weeks)

**Goal:** close the remaining L1 spec items I deleted in the Musk-cut. Everything the spec §1 demands is now in.

**Scope:**
- **Animator Controller parser:** states, transitions with conditions, parameter names + types. Adds `AnimState` nodes, `transitions_to` edges.
- **ShaderGraph parser:** inputs, outputs, keyword definitions, subgraph references. Minimal, additive.
- **Prefab variants:** detect `m_CorrespondingSourceObject`, emit `is_variant_of` edges. Walk overrides, emit `overrides` edges.
- **MCP tools v1:** `get_prefab_chain`, `get_neighbors`, `shortest_path`, `query_graph`. `query_graph` does simple entity-match + 2-hop BFS for now (full retrieval lives in L2, but this tool must exist for spec compliance).
- **`unitygraph build --update`:** file-mtime based. Re-parse only changed files, merge into existing `graph.json`.
- Update `graph.json` to `schema_version: "1.1"` — additive only.

**Gate:**
1. All 9 MCP tools from spec §1.6 respond correctly on all 4 projects
2. `--update` on a single-file change takes <1/10th of the full-build time
3. All spec §1.9 success criteria green

**Exit criterion:** **L1 ships.** Tag `v0.1.0`. Publish to PyPI as `unitygraph`. Open-source repo public. Write the L1 README and the CLAUDE.md/.mcp.json templates for end users.

---

### Iteration 4 — L2 retrieval skeleton (2 weeks)

**Goal:** given a task string and `graph.json`, produce a formatted context block.

**Scope:**
- **Entity extraction** (`inject/entities.py`): regex + graph-aware matching. Pull candidate entity names (PascalCase tokens, quoted strings) from the task. Match against node names. Rank by specificity.
- **Retrieval strategies** (`inject/retrieval.py`):
  - `entity_hop(entities, n_hops)` — BFS from matched nodes
  - `task_type(task_type_enum)` — map task type → set of edge types to expand along
  - `full_neighborhood(entities)` — god nodes (highest-degree) + 1-hop of mentioned entities
- **Task-type classifier:** cheap heuristic on task text (keywords: "fix"/"bug" → bug_fix, "add"/"implement" → new_feature, etc.). Deliberately dumb; replaced later if needed.
- **Formatter** (`inject/formatter.py`): produces the block shown in spec §2.4. Sections: SCENE DATA, COMPONENT RELATIONSHIPS, PREFAB CHAIN, LIFECYCLE NOTES, GRAPH CONFIDENCE, TOKEN USAGE.
- **Budget** (`inject/budget.py`): tiktoken-based count. Trimming strategy: drop lowest-rank subgraph nodes until under budget. Hard cap 1500 tokens (spec §2.7).
- **New CLI:** `unitygraph inject "<task text>" --graph graph.json [--strategy entity_hop|task_type|full] [--budget 1500]` → prints the block.
- **New MCP tool:** `inject_context(task: string, budget: int)` — exposed so Claude Code can pull context on demand mid-session.

**Gate:**
1. `inject` generates a valid block for 20 hand-written test tasks across 4 projects
2. All three strategies selectable and produce different (but valid) outputs
3. Context generation <2s (spec §2.7)
4. Token count never exceeds the `--budget` flag

**Exit criterion:** a developer can run `unitygraph inject "…" ` and get a usable block they would hand to Claude.

---

### Iteration 5 — UnityBench v1 (3 weeks)

**Goal:** 120-task benchmark, automated runner, first results.

This is the biggest iteration. It is the L2 research paper's data engine.

**Scope:**
- **Dataset construction** (`fixtures/UnityBench/`):
  - 40 Tier 1 tasks (isolated script) — smallest
  - 60 Tier 2 tasks (cross-artifact) — the core tier
  - 20 Tier 3 tasks (full-project)
  - Authored across 3 Unity projects (the 3 from I2)
  - Each task: `task.md` (prompt), `ground_truth.patch` (the correct diff), `metadata.yml` (tier, task_type, relevant nodes, metrics applicable)
- **Evaluation harness** (`evals/runner.py`):
  - Runs one task under one condition (baseline / manual_visual / unitygraph)
  - Captures Claude Code output diff
  - Runs Unity Test Runner in batch mode (`unity -batchmode -runTests`) to check runtime correctness
  - Computes the 5 metrics from spec §2.5
  - Writes results to `evals/results/<run_id>.jsonl`
- **Three conditions wired:**
  - **Baseline:** Claude gets only the task text and relevant source files. No MCP.
  - **Manual Visual:** human-authored scene description (pre-written per task) appended.
  - **UnityGraph:** L2 `inject_context` output appended.
- **Results dashboard:** simple `evals/report.py` → prints per-tier, per-condition, per-metric averages.

**Gate:**
1. All 120 tasks authored with ground truth
2. Runner executes all 360 trials (120 × 3) end-to-end in a single command
3. Tier 2, UnityGraph condition shows **≥30% improvement over Baseline on Runtime Correctness** (spec §2.7)
4. UnityGraph ≥ Manual Visual – 5pp on Tier 2 (spec §2.6 claim: closes the gap)

**Exit criterion:** **L2 research result.** First paper draftable. Tag `v0.2.0`.

If gate 3 fails: do not proceed to L3. Iterate on L2 retrieval strategies until it passes or until ablation proves which retrieval variant matters. The spec is clear — L3 only starts after L2 validated.

---

### Iteration 6 — L2 polish + product packaging (1 week)

**Goal:** L2 ships as a sellable "Unity-aware Claude Code skill" (spec §6).

**Scope:**
- Claude Code skill manifest (`.claude/skills/unity-aware/`) that wraps the L2 CLI
- Caching (`inject/cache.py`): memoize `inject_context` by `(task_hash, graph_hash, strategy)`
- Confidence scoring: nodes with full Inspector data → HIGH; nodes with only code data → MEDIUM; inferred → LOW. Emitted in the block.
- Polish: better entity extraction (small spaCy model or llm-based fallback), better formatter (markdown tables where useful)
- Docs: `README_L2.md` with install, skill usage, benchmark numbers

**Gate:** L2 usable as a drop-in Claude Code skill in a fresh Unity project without editing code.

**Exit criterion:** **L2 product ships.** Tag `v0.3.0`.

---

### Iteration 7 — L3 observation loop (2 weeks)

**Goal:** passive logging. Every Claude Code Unity session's inputs and outputs recorded.

**Scope:**
- **Observer** (`behavior/observer.py`): hooks into Claude Code via a user-level hook (or MCP middleware — decide at implementation time based on what the platform exposes). Logs per session:
  - `task_text`, `injected_context`, `claude_output_diff`, `timestamp`, `graph_hash`, `session_id`
  - Writes to `.unitygraph/sessions/<session_id>.jsonl`
- **Feedback CLI:**
  - `unitygraph feedback --correct [--session ID]`
  - `unitygraph feedback --incorrect --note "…" [--session ID]`
- **Implicit feedback:** watch `.git` — if Claude's diff is committed within 24h, infer accept. If reverted, infer reject.
- **Correction capture:** on `feedback --incorrect`, diff original output vs. current file state, store as `correction.patch`.

**Gate:**
1. Run 10 real Unity tasks through Claude Code with observer active; all 10 logged with complete fields
2. Feedback CLI round-trips correctly
3. Implicit feedback detection has ≥90% precision on a labeled test set of 20 diffs

**Exit criterion:** sessions collecting reliably. Data pipeline for L3 live.

---

### Iteration 8 — L3 failure pattern map (2 weeks)

**Goal:** turn session logs into the pattern map, seed with the 6 known patterns, start validating.

**Scope:**
- **Pattern schema** (`schemas/pattern.json`): per spec §3.4 fields (`pattern_id`, `task_type`, `trigger`, `missing_context_type`, `injection_rule`, `confidence`, `evidence_count`, `last_seen`, `project_scope`)
- **Pre-seed loader** (`behavior/patterns.py`): loads the 6 patterns from spec §3.5 at first run with `confidence: 0.3, evidence_count: 0`
- **Delta extractor** (`behavior/delta.py`): for each `--incorrect` session, runs an LLM-assisted comparison of `claude_output` vs `correction` → suggests which `missing_context_type` would have prevented the error. Outputs a candidate pattern update.
- **Pattern promoter:** moves candidates from `observed` → `active` once `evidence_count ≥ 5` and `confidence ≥ 0.6` (spec §3.8).
- **Pattern store:** SQLite at `.unitygraph/patterns.db` (small, local, easy to inspect).
- **CLI:**
  - `unitygraph patterns list`
  - `unitygraph patterns show <id>`
  - `unitygraph patterns promote <id>` (manual override)

**Gate:**
1. Pre-seeds loaded, listable, inspectable
2. Delta extractor produces sensible pattern candidates on a labeled set of 20 sessions
3. After running I5's UnityBench Tier 2 failures through the extractor, at least 3 of the 6 pre-seeds have `evidence_count ≥ 5`

**Exit criterion:** pattern map populating from real data.

---

### Iteration 9 — L3 adaptive injection (2 weeks)

**Goal:** L2's retrieval is now influenced by the pattern map.

**Scope:**
- **Pattern matcher** (`behavior/matcher.py`): given a task + extracted entities, returns the list of active patterns that fire (match on `trigger` regex/features).
- **L2 integration:** `inject_context` consults the matcher before retrieval. Each matched pattern's `injection_rule` modifies the retrieval (e.g., "always include parent-component data for physics scripts" → expand physics-tagged nodes by +1 hop).
- **Pattern decay:** patterns not triggered in 30 days and with `confidence < 0.5` → archived automatically.
- **A/B on injection:** 50% of sessions run L2-only, 50% run L2+L3, logged for comparison. The observer records which condition produced which output.

**Gate:**
1. Adaptive injection produces different context blocks from static injection when a pattern fires (verified on ≥5 tasks)
2. UnityBench Tier 2 re-run: L3-adaptive condition shows measurable improvement over L2-static (target: ≥5pp on Runtime Correctness)
3. At least 3 of the 6 pre-seeded patterns have `confidence > 0.6` per spec §3.8

**Exit criterion:** **L3 research result.** Flagship paper draftable. Tag `v0.4.0`.

---

### Iteration 10 — Bundle, docs, release (1 week)

**Goal:** full UnityGraph system shippable as spec §6 bundle.

**Scope:**
- Single `pip install unitygraph[full]` installs L1+L2+L3
- Unified `unitygraph init` in a Unity project: writes `CLAUDE.md`, `.mcp.json`, `.unitygraph/config.yml`
- End-to-end README with install, quickstart, each layer's CLI
- License split: L1 OSS, L2/L3 commercial. Package boundary enforces this.
- UnityBench dataset released (CC-BY) separately — it is the paper's artifact.
- Three papers' supplementary materials bundled: `papers/L1_schema_comparison.md`, `papers/L2_unitybench.md`, `papers/L3_behavior_model.md` (data + methodology stubs; full papers written externally).

**Gate:** fresh user in a new Unity project can `pip install unitygraph && unitygraph init && unitygraph build . && unitygraph serve graph-out/graph.json` and Claude Code uses all three layers in one session.

**Exit criterion:** **v1.0.0 shipped.**

---

## 4. Cross-cutting workstreams

Running in parallel to iterations, not blocking them.

### 4.1 Testing strategy

| Level | Coverage target | When |
|---|---|---|
| Unit (parsers, formatters) | 80% | Every iteration |
| Integration (parser→graph→MCP) | Key paths | From I1 |
| E2E (Claude Code session) | Headline test per layer | I1, I6, I9 |
| Benchmark (UnityBench) | All 120 tasks | I5 onward |

### 4.2 Performance budgets (enforced in CI from I2)

- `build` on 50-script project: <60s
- `build --update` single-file: <6s
- MCP tool response: <500ms median
- `inject` context generation: <2s
- Context token output: <1500

### 4.3 Error-handling policy

Boundary-only validation. Parse failures on a single file never abort the build — log, skip, continue. Inside the pipeline, trust the data. User-facing CLI always exits with a clear error message and non-zero code on total failure.

### 4.4 Research artifacts timeline

- **I5 close:** L2 paper data complete → draft paper (target ASE/ICSE 2027 cycle)
- **I9 close:** L3 paper data complete → draft paper (target ICSE/NeurIPS 2027 cycle)
- **I10 close:** L1 paper (schema comparison) — smaller, MSR target

### 4.5 Product release gates (spec §6)

| Milestone | Iteration | Channel |
|---|---|---|
| L1 OSS | I3 | PyPI + GitHub public |
| L2 commercial | I6 | RinvalAI store, one-time license |
| L3 commercial premium | I9 | RinvalAI store, higher tier |
| Full bundle | I10 | RinvalAI store, bundle + commercial rights |

---

## 5. Timeline summary

| Iteration | Weeks | Cumulative | Ships |
|---|---|---|---|
| I0 Bootstrap | 0.5 | 0.5 | |
| I1 L1 vertical slice | 2 | 2.5 | |
| I2 L1 robustness | 1.5 | 4 | |
| I3 L1 completeness | 1.5 | 5.5 | **L1 v0.1.0** |
| I4 L2 skeleton | 2 | 7.5 | |
| I5 UnityBench | 3 | 10.5 | **L2 v0.2.0** |
| I6 L2 product | 1 | 11.5 | **L2 product** |
| I7 L3 observation | 2 | 13.5 | |
| I8 L3 patterns | 2 | 15.5 | |
| I9 L3 adaptive | 2 | 17.5 | **L3 v0.4.0** |
| I10 Bundle | 1 | 18.5 | **v1.0.0** |

**~18-19 working weeks end-to-end.** No buffer baked in on purpose — each iteration's gate is the buffer. If a gate fails, that iteration extends; the next does not start.

---

## 6. Risk register (top 5)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Unity YAML edge cases break scene parser on real projects | High | High | I2 is dedicated to this; 3 real projects, not toys |
| L2 retrieval doesn't hit 30% improvement | Medium | High | I5 gate stops the train; we iterate on retrieval before L3 |
| UnityEvent GUID resolution is hairier than expected | Medium | Medium | Time-box in I1 to 3 days; if over, stub `get_event_connections` to return empty and revisit in I2 |
| MCP SDK changes break server | Low | Medium | Pin SDK version; upgrade deliberately between iterations |
| L3 observer can't reliably capture sessions | Medium | High | I7 gate is observer reliability; if under 90% capture, pivot to explicit-feedback-only before I8 |

---

## 7. Decision log (decisions I'm locking in now)

1. **Python 3.11+.** Type hints everywhere, `mypy --strict` on `src/`.
2. **tree-sitter for C#**, not a Roslyn bridge. Good-enough parsing, no .NET dependency.
3. **PyYAML + Unity tag monkey-patch** for YAML, not a custom parser. `ruamel.yaml` only if PyYAML breaks on real projects in I2.
4. **SQLite for the pattern store**, not a server DB. Local, inspectable, version-controllable if needed.
5. **MCP stdio transport**, not HTTP. Simpler, matches spec's `.mcp.json` example.
6. **One package, multiple subcommands.** Not three separate packages. Commercial/OSS split handled via license headers and build-time subsets, not separate repos.
7. **Claude designs schemas** (node fields, pattern fields) at implementation time. This plan only freezes top-level shapes.
8. **Single fixture project drives I1 correctness; three real projects drive I2 robustness; UnityBench drives I5+ research.** Different purposes, different fixtures.

---

## 8. Ready-to-start checklist for I0

- [ ] Initialize git repo in `d:/Rnival-PRs/UnityGraph/`
- [ ] Create `pyproject.toml` with declared deps
- [ ] Scaffold `src/unitygraph/` per §1
- [ ] Author `fixtures/MiniUnityProject/` (hand-roll the YAML; do not use Unity Editor)
- [ ] Set up GitHub Actions CI
- [ ] Run `unitygraph --help` successfully
- [ ] Open I1 branch

I0 starts the moment you give the word. On your go, I begin.
