# Paper L2 — UnityBench: Graph Injection Closes the Scene-Code Gap

**Research question (per spec §2.6):** Which graph retrieval strategies
produce the best LLM performance on Unity tasks, and at what token cost?
Does automated graph injection match human-supplied visual context?

## Thesis

The performance gap between LLMs given only code and LLMs given code +
scene context on Unity-specific tasks is a *structured context availability*
problem, not a model capability problem. A token-budgeted graph-injection
system can close most of that gap automatically, without human intervention
per task.

## Claimed contribution

1. **UnityBench** — a benchmark of 120 Unity coding tasks organized into
   three tiers (isolated script, cross-artifact, full project) with
   ground-truth patches and automated scoring. MVP version (19 tasks)
   ships with this release; full version is additive scale-up.
2. A **three-condition evaluation** (baseline, manual_visual, unitygraph)
   isolating the contribution of scene context.
3. A **three-strategy ablation** (entity_hop, task_type, full_neighborhood)
   showing which retrieval style wins on which task types.
4. **Token-efficiency** characterization: how much context-to-task ratio
   does automated injection incur vs human-authored visual description.

## Evidence

- `evals/unitybench/` — harness, 19 MVP tasks, runner, report generator.
- `tests/unit/test_unitybench.py` — static-scoring correctness test.
- `README_L2.md` — user-facing writeup with benchmark running instructions.

## I5 + I9 gates (from the plan)

- **I5 gate:** unitygraph condition shows ≥30% relative improvement over
  baseline on Tier 2 runtime_correctness. *Requires real Claude API key;
  pending an experimental run.*
- **I9 gate:** unitygraph_adaptive shows ≥5pp absolute improvement over
  unitygraph (static L2). Same dependency.

The benchmark infrastructure is complete and validated via dry-run
(57-trial sweep). Real-API gate runs follow the ANTHROPIC_API_KEY
availability.

## Design decisions documented

- **Static patch-scoring instead of Unity Test Runner** for the MVP.
  Paper-grade requires Unity Editor installed on CI; that path is wired
  (the plan §I5 specifies `unity -batchmode -runTests`) but scope-scaled
  out of this release.
- **Prompt caching** on the shared system prompt across trials — cuts a
  57-trial Sonnet 4.6 sweep to ~$2-5 end-to-end.
- **Programmatic scene descriptions** for the manual_visual condition in
  the MVP — acts as an oracle reference. The paper-grade version swaps
  in hand-written developer descriptions.

## Venue fit

- **ASE** — tool + benchmark paper.
- **ICSE** — stronger venue if the paper-grade 120-task + Unity Test Runner
  results land.

## Status

- Harness complete; scoring unit-tested.
- 19-task MVP authored with ground-truth patches.
- Paper-grade 120-task scale-up + Unity Test Runner integration deferred
  until Unity Editor is available on the benchmark host.
- Real-API gate run pending API key.
