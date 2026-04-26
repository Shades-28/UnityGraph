# Bake-off Scorecard — clash.io, 8 questions, 2 configs

Same questions, same project, same agent (me, Claude). Only the tool set
differs. Ground truth verified manually before either run.

Legend: ✅ correct + complete · 🟡 partial · ⚠️ honest hedge ·
❌ wrong / incomplete · 🟦 tie

---

| #  | Tier | Question | Baseline | UnityGraph | Winner |
|----|------|----------|----------|------------|--------|
| Q1 | 1    | What does SpawnEnemy() do? | ✅ accurate sentence summary | 🟡 only structural facts (file/line + outbound calls) | **Baseline** |
| Q2 | 1    | EnemyBase parent class? | ✅ MonoBehaviour | ✅ MonoBehaviour | 🟦 Tie |
| Q3 | 2    | Callers of GetComponent<EnemyBase>? | ✅ 1, EnemyController:80 | ✅ 1, EnemyController.SpawnEnemy:80 | 🟦 Tie (UnityGraph adds containing method "for free") |
| Q4 | 2    | CharacterBehaviour → CharacterAnimator method calls? | ✅ 8 (manually filtered comments) | ✅ 8 with snippets | 🟦 Tie (UnityGraph already excludes comments) |
| Q5 | 3    | Actual spawnRadius value vs code default? | ✅ 10 vs 12f, didn't match | ✅ 10 vs 12f + bonus: also surfaced despawnRadius and drawDebugRadius overrides | **UnityGraph** (more complete) |
| Q6 | 3    | UnityEvent listeners on RateUsScript? | ✅ 2 methods, 6 bindings | ✅ 2 methods, 6 bindings | 🟦 Tie — but: baseline only worked because clash.io's prefab YAML helpfully includes m_TargetAssemblyTypeName. Older Unity versions or stripped-script prefabs would fail baseline. |
| Q7 | 3    | Missing script references count? | ⚠️ "Cannot answer with confidence — would need to enumerate every guid in scenes/prefabs and cross-reference" | ✅ 49 placeholders, top guid attached to 359 GameObjects | **UnityGraph** (decisive) |
| Q8 | 4    | Rename CharacterAnimator.SetAnimation — what breaks? | ✅ 8 code callers (CharacterBehaviour + EnemyMelee), 0 UnityEvent listeners | ❌ 4 code callers (only CharacterBehaviour), 0 UnityEvent listeners — **missed EnemyMelee's 4 calls** | **Baseline** (UnityGraph's C# parser missed inherited field types) |

---

## Tally

| Outcome | Baseline | UnityGraph |
|---------|----------|------------|
| ✅ Correct + complete | 6 | 5 |
| 🟡 Partial            | 0 | 1 (Q1) |
| ⚠️ Honest hedge       | 1 (Q7) | 0 |
| ❌ Wrong / incomplete | 0 | 1 (Q8) |
| **Wins**              | 2 (Q1, Q8) | 2 (Q5, Q7) |
| **Ties**              | 4 (Q2, Q3, Q4, Q6) | |

---

## What this actually tells us

### UnityGraph wins on the questions it was built for

- **Q5** (Inspector overrides) and **Q7** (missing scripts) are exactly
  the scene-code-gap questions UnityGraph was built to answer. Baseline
  stalled on Q7 (correctly hedging rather than guessing); UnityGraph
  answered in one query.
- **Q5 bonus**: UnityGraph surfaced two *additional* overrides
  (despawnRadius, drawDebugRadius) the question didn't ask about — the
  kind of "by the way, you should also know..." that source-only
  answers can't give.

### UnityGraph's "tie" wins are quality wins, not equality

- **Q3, Q4**: same answer, but UnityGraph's includes containing-method
  context and pre-filtered out commented-out code. Baseline grep needed
  manual filtering for comments.
- **Q6**: tied on this project, but the baseline only worked because
  the prefab YAML included `m_TargetAssemblyTypeName: RateUsScript`
  next to each `m_MethodName`. Without that hint (older Unity, stripped
  scripts, or a project that uses a different binding style), baseline
  would need to chase fileIDs through the prefab — UnityGraph wouldn't.

### UnityGraph's losses expose real product issues

- **Q1**: UnityGraph stores method *signatures* and *call sites*, not
  method *bodies*. For "what does this method do?" you still need to
  read the source. UnityGraph correctly gave you the file:line anchor —
  but it can't summarize semantics. **Not a bug, a scope decision.**
- **Q8**: This one is a **real bug**. UnityGraph's C# parser didn't
  resolve `animator.SetAnimation(...)` in EnemyMelee.cs because
  `animator` is declared on the parent class `EnemyBase`, not on
  EnemyMelee itself. The parser only walks field declarations on the
  current class. This means `who_uses` and `impact_of` queries give
  **incomplete answers on any project that uses inheritance** — and
  that's most Unity projects.

---

## The honest verdict

**Baseline can answer most questions** if the developer is patient,
knows where to grep, and accepts the tedium. **UnityGraph's win condition
isn't "answers questions baseline can't"** — it's "answers in one query
what would take baseline 10 grep iterations, and never gets fooled by
comments / stripped m_TargetAssemblyTypeName / scene YAML structure."

**On scene-code-gap questions specifically (Q5, Q7), UnityGraph is not
just faster — baseline literally hedged on Q7.** That's the real
product moat: an AI agent on baseline tools will either spend hours
reimplementing UnityGraph's guid index, or guess. Both bad.

**Q8 is the action item.** The C# parser's field-type resolution must
walk up the inheritance chain. This is the next concrete bug to fix in
v2.1.2.

---

## What I'd improve about this test

1. **More inheritance-heavy questions.** Q8's failure suggests there
   are more hidden incompleteness bugs in `who_uses` / `impact_of`
   that 8 questions can't surface.
2. **Run on a project where the developer literally does not know the
   codebase.** Both runs had me, who already knew clash.io's structure
   from earlier in the session. A cold-read agent would struggle more
   on baseline (especially Q5: would they think to grep `.unity` files?)
   and lean harder on UnityGraph.
3. **Time the answers.** Token cost / wall time per answer would show
   the productivity multiplier even when both produce correct answers.
