# UnityBench

A benchmark for measuring whether UnityGraph's context injection improves
Claude's performance on Unity-specific coding tasks.

## Method

Each task is given to Claude under three conditions:

1. **baseline** — task text + the single source file the task references.
   No scene data, no MCP access.
2. **manual_visual** — task + file + a human-authored scene description
   (the "oracle" condition: upper-bound when a human manually bridges the
   scene-code gap).
3. **unitygraph** — task + file + a Layer-2-generated UNITYGRAPH CONTEXT
   block. Same retrieval pipeline Claude would hit via the MCP tool.

The hypothesis (spec §2.6): condition 3 closes most of the gap between 1
and 2 without any human intervention.

## Tiers

| Tier | Name | Description | N (MVP) | N (paper) |
|------|------|-------------|---------|-----------|
| 1 | Isolated Script | Solvable from code alone — baseline should perform well | 20 | 40 |
| 2 | Cross-Artifact | Requires scene/Inspector data — the core tier | 30 | 60 |
| 3 | Full Project | Requires understanding multiple systems at once | 10 | 20 |
| | **Total** | | **60** | 120 |

The MVP author set ships with the commit; scaling to the paper-grade 120 is
additive and doesn't change the harness.

## Metrics

Per spec §2.5:

1. **Runtime correctness** — does the patch actually implement the
   intended behavior? In the MVP we use static checks (patch applies, names
   resolve, compiles via `dotnet build`). Paper-grade requires Unity Test
   Runner; that's wired but skipped when Unity isn't available.
2. **Component awareness** — does the solution reference co-components
   the task implicitly depends on?
3. **Lifecycle correctness** — does the solution respect script execution
   order if multiple scripts are involved?
4. **Inspector awareness** — does the solution use Inspector-set values
   rather than code defaults when they diverge?
5. **Token efficiency** — tokens of context injected vs tokens Claude
   actually referenced in its response.

Metrics 2-5 are judged by keyword / AST matching against the ground-truth
patch, not semantic LLM grading. Noisy but reproducible.

## Running

### 1. Build the graphs the tasks reference

```bash
unitygraph build fixtures/MiniUnityProject   # MVP tasks live against this
# When you scale up to the paper-grade dataset:
# unitygraph build "D:/PR/Unity/Indian-Bike-Gangster-3D" -o evals/unitybench/graphs/Indian-Bike
# unitygraph build "D:/PR/Unity/clash.io"              -o evals/unitybench/graphs/clash
```

### 2. Dry-run (no API key needed)

This validates prompts, the scoring pipeline, and the report generator without
calling Claude. Scores come out as 1.0 because the harness scores the ground
truth against itself in dry-run.

```bash
python -m evals.unitybench.runner --dry-run
python -m evals.unitybench.report
```

### 3. Real benchmark

Set `ANTHROPIC_API_KEY`, then:

```bash
# Full sweep: 19 tasks x 3 conditions = 57 trials. Budget ~$2-5 on Sonnet 4.6.
python -m evals.unitybench.runner

# One specific task x condition:
python -m evals.unitybench.runner --task t2_001_slow_proportional_to_speed --condition unitygraph

# Report the latest run
python -m evals.unitybench.report
```

The runner uses prompt caching on the shared system prompt, so the second
trial onward reads cached tokens (~90% cheaper for that portion).

### Expected I5 gate signal

If the L2 retrieval actually helps (it should on `requires_scene_context: true`
tasks), the `unitygraph` condition's Tier-2 runtime_correctness should land
meaningfully above the `baseline` condition's. The report flags PASS when the
delta is >= 30% relative improvement.

## Layout

```
evals/unitybench/
├── README.md                    # this file
├── runner.py                    # orchestrates (task, condition) -> claude -> score
├── report.py                    # aggregates results/*.jsonl into tier x condition x metric tables
├── tasks/
│   ├── t1_*/                    # 20 Tier 1 tasks
│   │   ├── task.md              # prompt + source file path reference
│   │   ├── metadata.yml         # tier, project, relevant_entities, graph_path
│   │   └── ground_truth.patch   # unified diff of the correct fix
│   ├── t2_*/                    # 30 Tier 2 tasks
│   └── t3_*/                    # 10 Tier 3 tasks
├── graphs/                      # pre-built graph.json per reference project
├── conditions/
│   ├── baseline.py              # no context
│   ├── manual_visual.py         # graph.json -> human-style scene description
│   └── unitygraph.py            # graph.json -> inject_context()
├── metrics/                     # one module per metric
└── results/                     # <run_id>.jsonl
```
