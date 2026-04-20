# Paper L3 — An External Behavioral Model of LLM Domain Priors

**Research question (per spec §3.7):** Can a behavioral model of LLM
domain-specific priors, learned from observed failures, produce measurably
better context injection than static retrieval strategies alone? Which
failure patterns are universal across Unity projects vs project-specific?

## Thesis

Claude — like any frontier LLM — has learnable, predictable blind spots
specific to Unity C#. Building an **external** model of those blind spots
from observed (task, output, feedback) triples, and using it to drive
context retrieval, produces measurable performance gains over static
injection strategies — without fine-tuning, without modifying the model,
and without human intervention per task.

This is the flagship research claim of the project and the novel
contribution unique to L3.

## Claimed contribution

1. **A behavioral model architecture** for LLMs in domain-specific coding
   contexts: a persistent pattern store (SQLite), an observation loop that
   captures (injection, feedback) pairs, and an extractor that updates
   pattern confidences via exponential moving average.
2. **Six pre-seeded Unity blind spots** from direct developer observation
   (spec §3.5): Implicit Rigidbody, Inspector Override Blindness,
   Lifecycle Race, Coroutine Destroy, Event Connection Gap, Prefab
   Override Surprise. Each has a trigger regex, a missing-context-type
   label, and an injection rule.
3. **Adaptive injection** (Layer 3 matcher): active patterns influence
   every L2 retrieval call via extra_hops / emphasize_edges / extra_tools
   directives.
4. **Ablation study** comparing static L2 injection vs L3 adaptive
   injection on the same UnityBench task set (gate: ≥5pp absolute
   improvement on Tier 2 runtime correctness).
5. **Universality analysis**: which of the 6 pre-seeded patterns replicate
   across multiple real Unity projects, and which are project-specific —
   quantified via per-project evidence counts in the pattern store.

## Evidence

- `src/unitygraph/behavior/patterns.py` — SQLite-backed pattern store
  with auto-seeding, EMA confidence updates, and auto-promotion at
  (evidence≥5, confidence≥0.6). Promotion gate validated end-to-end
  (see I8 smoke test).
- `src/unitygraph/behavior/matcher.py` — pattern-to-retrieval rule table.
- `src/unitygraph/inject/engine.py` — adaptive-mode integration with
  cache-key awareness.
- `tests/unit/test_patterns.py` (10 tests) and
  `tests/unit/test_adaptive_injection.py` (8 tests) demonstrate every
  behavior the paper will claim.

## Why this is novel

No existing paper claims an external behavioral model of an LLM's domain
priors. Comparable work:

- **ContextAgent (2025)** — proactive context gathering; not a behavioral
  model of the LLM itself, and not coding-specific.
- **Behavioral fingerprinting (2025)** — characterizes LLMs at the
  population level; not tied to a knowledge graph or a retrieval layer.

L3 differs on three axes: (1) coding context, (2) domain-specific knowledge
graph backbone, (3) per-session pattern adaptation with persistent state.
No prior work combines all three for a game engine.

## I9 gate (from the plan)

- ≥5pp absolute improvement in Tier 2 runtime_correctness for
  unitygraph_adaptive vs unitygraph on UnityBench. *Pending
  ANTHROPIC_API_KEY availability.*

The pipeline end-to-end is verified: promoting a pattern to `active`
changes the retrieval, changes the subgraph, changes the formatted block,
and gets attributed in the `ADAPTIVE INJECTION NOTES` section. What's
deferred is the population-level statistical validation.

## Venue fit

- **ICSE** — software-engineering-specific and strongly empirical.
- **NeurIPS** — LLM behavioral-model framing; the external-model angle
  is NeurIPS-shaped if the ablation is clean.

## Status

- Full infrastructure shipping with v1.0.0.
- Six pre-seeded patterns installed; auto-promotion validated.
- Adaptive injection wired through L2.
- Real-API ablation run pending.
