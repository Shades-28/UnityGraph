# Clash.io — 16-question results

Both runs answered each question on clash.io. Verdicts vs. ground truth.

| #   | Tier | Question | Baseline | UnityGraph | Winner |
|-----|------|----------|----------|------------|--------|
| Q1  | 1    | What does SpawnEnemy() do? | ✅ accurate one-line summary | 🟡 only structural facts | **Baseline** |
| Q2  | 1    | EnemyBase parent class? | ✅ MonoBehaviour | ✅ MonoBehaviour | 🟦 Tie |
| Q3  | 2    | Callers of GetComponent<EnemyBase>? | ✅ 1, EnemyController:80 | ✅ 1 + containing method | 🟦 Tie |
| Q4  | 2    | CharacterBehaviour → CharacterAnimator method calls? | ✅ 8 (after manually filtering 2 comments) | ✅ 8 with snippets, comments pre-excluded | 🟦 Tie (UG slightly cleaner) |
| Q5  | 3    | Actual spawnRadius value? | ✅ 10 vs 12f | ✅ 10 vs 12f + 2 bonus overrides | **UnityGraph** |
| Q6  | 3    | UnityEvent listeners on RateUsScript? | ✅ 6 bindings, 2 methods | ✅ 6 bindings, 2 methods | 🟦 Tie |
| Q7  | 3    | Missing scripts count? | ⚠️ "cannot answer with confidence" | ✅ 49 placeholders | **UnityGraph** |
| Q8  | 4    | Rename SetAnimation impact? | ✅ 8 callers | ✅ 8 callers (after v2.1.2 fix) | 🟦 Tie |
| Q9  | 1    | Health property/field on EnemyBase? | ✅ neither, only maxHealth/currentHealth | ✅ no field, no method "Health" | 🟦 Tie |
| Q10 | 2    | List<UserType>? | ✅ 5-6 in _Assets/Scripts | ✅ 15 across whole project | **UnityGraph** (more comprehensive) |
| Q11 | 1    | Async methods? | ✅ 0 in user code | 🟡 "graph doesn't track return types" | **Baseline** |
| Q12 | 2    | IPointerClickHandler implementers? | ✅ 3 | ✅ 3 | 🟦 Tie |
| Q13 | 3    | Scopes referencing CharacterAnimator? | ✅ 4 (1 scene + 3 prefabs) | ✅ 4 (same) | 🟦 Tie |
| Q14 | 3    | EnemyController scalar overrides count? | ✅ 2-3 (drawDebugRadius edge case) | ✅ 3 | 🟦 Tie |
| Q15 | 4    | Subclasses of EnemyBase + dependencies? | ✅ 1 subclass + 5 method calls | ✅ 1 subclass + 5 method calls (with file:line) | 🟦 Tie |
| Q16 | 4    | String-based dispatch? | ✅ 0 in user code | ✅ honest "cannot determine" | 🟦 Tie |

**Tally:**
- Baseline: 13✅ + 1🟡 + 1⚠️ + 0❌ + wins on Q1, Q11
- UnityGraph: 12✅ + 2🟡 + 0❌ + wins on Q5, Q7, Q10

**Net per project: 11 ties, 2 baseline wins, 3 UnityGraph wins.**

Critical observations:
- **clash.io is small and clean** — most questions have answers easily reachable by both. The bake-off would be more discriminating on a larger project.
- **Both runs converge on most questions, but UnityGraph wins are the ones a Unity dev cares about most**: Inspector overrides (Q5), missing scripts (Q7), comprehensive cross-asset queries (Q10).
- **Baseline wins where UnityGraph genuinely doesn't track the data** (Q1 method bodies, Q11 return types). These are scope decisions.
- **Q16 is interesting**: UnityGraph honestly admitted "I don't track string dispatch" — the kind of "I don't know" that's better than guessing.
