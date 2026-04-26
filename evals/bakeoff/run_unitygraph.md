# Run B — WITH UNITYGRAPH

Same questions, answered using only the UnityGraph queries module
against the loaded `graph.json`. No file reads, no greps.

---

## Q1 — What does EnemyController.SpawnEnemy() do?

The graph alone gives only structural info: SpawnEnemy is a method on
EnemyController defined at line 74, ends line 84, contains one outbound
call site (`get_component` of EnemyBase via `enemy.GetComponent<EnemyBase>()`).
This is *less* than what reading the source gave us — UnityGraph stores
relationships, not method bodies.

For a one-sentence summary, you'd still want the source. UnityGraph
points you at the file:line.

**Confidence:** structural answer high, semantic summary requires source.

---

## Q2 — What class does EnemyBase inherit from?

`MonoBehaviour` (from EnemyBase node's `base_class` field).

**Confidence:** high.

---

## Q3 — Who calls GetComponent<EnemyBase>()?

`EnemyController.SpawnEnemy` at
`Assets\_Assets\Scripts\Enemy\EnemyController.cs:80`. One caller.
`who_uses(EnemyBase)` returned this directly with site evidence.

**Confidence:** high.

---

## Q4 — Distinct method calls CharacterBehaviour makes on CharacterAnimator?

8 method_call sites on the `depends_on` edge from CharacterBehaviour →
CharacterAnimator. Each carries file:line:snippet.

**Confidence:** high.

---

## Q5 — Actual spawnRadius on EnemyController?

`inspector_overrides_for(EnemyController)` returned three scalar
overrides on the EnemyController GameObject:
- `spawnRadius = 10` (code default `12f`)
- `despawnRadius = 12` (code default `20f`)
- `drawDebugRadius = 1` (code default `true`)

So spawnRadius is **10 at runtime, NOT matching the code default**.
The query also surfaced two related overrides I wasn't asked about,
which is useful context.

**Confidence:** high.

---

## Q6 — Methods on RateUsScript bound as UnityEvent listeners?

`event_listeners(RateUsScript)` returned 6 listener bindings across
2 distinct methods:
- `OpenRateUsPage` (1 binding)
- `RateUsGame` (5 bindings)

All in `Assets\_Assets\Prefab\Rate_Us\Rate_Us_Panel.prefab` at lines
435, 567, 699, 831, 1316, 1448.

**Confidence:** high.

---

## Q7 — GameObjects with broken/missing script references?

`find_missing_scripts(g)` returned **49 distinct missing-script
placeholders** with live attachments. Top 5 by impact:
- `fe87c0e1…` — 359 GameObject attachments
- `f5f67c52…` — 236 attachments
- `f70555f1…` — 122 attachments
- `5f7201a1…` — 113 attachments
- `f4688fdb…` — 52 attachments

**Confidence:** high. This is the question baseline couldn't answer.

---

## Q8 — Rename CharacterAnimator.SetAnimation, what breaks?

Code call sites on CharacterAnimator.SetAnimation: **4**
- `CharacterBehaviour.UpdateMovementAnim @ CharacterBehaviour.cs:57`
- `CharacterBehaviour.UpdateMovementAnim @ CharacterBehaviour.cs:61`
- `CharacterBehaviour.StartClimb @ CharacterBehaviour.cs:69`
- `CharacterBehaviour.StopClimb @ CharacterBehaviour.cs:70`

UnityEvent listeners on SetAnimation: **0**.

**MISSED:** UnityGraph's `depends_on` edge from `EnemyMelee →
CharacterAnimator` does NOT exist in the graph. The C# parser apparently
didn't resolve `animator.SetAnimation(...)` in EnemyMelee to
CharacterAnimator (likely because `animator` is inherited from
EnemyBase's parent class, and the parser only resolves field types
declared on the same class). Baseline caught EnemyMelee via grep;
UnityGraph missed it.

**Confidence:** high on UnityEvent answer; INCOMPLETE on code callers.

---

## Honest summary

UnityGraph won decisively on Q5, Q6, Q7. Tied on Q2, Q3, Q4. Lost on
Q1 (no method bodies) and Q8 (cross-class field resolution gap in the
C# parser — a real bug).
