# Run A — BASELINE (Read / Glob / Grep only)

Answers given without consulting `graph.json` or any UnityGraph query.
Tools available: Read, Glob, Grep on `D:/PR/Unity/clash.io/`.

---

## Q1 (Tier 1) — What does EnemyController.SpawnEnemy() do?

For each requested spawn it grabs an enemy GameObject from the pool
(`PoolingController.Instance.GetEnemy(enemyType)`), fetches its
`EnemyBase` component, positions it offscreen via
`GetSpawnPositionOutsideScreen(_player.position)`, and calls
`Initialize(_player)` on it.

**Confidence:** high. Single file read.

---

## Q2 (Tier 1) — What class does EnemyBase inherit from?

`MonoBehaviour`.

**Confidence:** high.

---

## Q3 (Tier 2) — Which scripts call GetComponent<EnemyBase>()?

One caller — `EnemyController` at
`Assets/_Assets/Scripts/Enemy/EnemyController.cs:80`, inside the
`SpawnEnemy` method (declared at line 75).

**Confidence:** high. Direct grep.

---

## Q4 (Tier 2) — Distinct method calls CharacterBehaviour makes on CharacterAnimator?

8 live call sites (lines 48, 49, 53, 54, 57, 61, 69, 70). Two additional
references on lines 21 and 26 are inside comments and don't count.

**Confidence:** high.

---

## Q5 (Tier 3) — Actual spawnRadius on EnemyController in the scene?

Code default is `12f`. Scene value (in
`Assets/_Assets/Scene/DevScene.unity:709`) is `10`. **They don't match —
the Inspector overrides the code default.**

**Confidence:** high, but only because I knew to grep `.unity` files.
A pure-source-code reader would have stopped at `12f` and been wrong.

---

## Q6 (Tier 3) — Which methods on RateUsScript are bound as UnityEvent listeners?

Two distinct methods: `OpenRateUsPage` (1 binding) and `RateUsGame`
(5 bindings). 6 total bindings, all in
`Assets/_Assets/Prefab/Rate_Us/Rate_Us_Panel.prefab` at lines 440, 572,
704, 836, 1321, 1453.

**Confidence:** high. Helped that the prefab includes
`m_TargetAssemblyTypeName: RateUsScript` next to each `m_MethodName`,
confirming the target. Without that, I'd have had to chase fileIDs.

---

## Q7 (Tier 3) — GameObjects with broken/missing script references?

**Cannot answer with confidence.** The check requires enumerating every
`m_Script: {fileID: 11500000, guid: <X>}` reference in scenes/prefabs
(thousands of them, hundreds of unique guids), then for each guid
checking whether a matching `.cs.meta` file exists in the project. With
only Read/Glob/Grep, this is many hours of iterative tool calls; in
practice I'd be approximating UnityGraph's guid index by hand.

**Confidence:** can't answer. Hedging rather than guessing.

---

## Q8 (Tier 4) — Renaming CharacterAnimator.SetAnimation, what breaks?

**Code call sites** (8 total):
- `CharacterBehaviour.cs:57, 61, 69, 70`
- `EnemyMelee.cs:229, 280, 285, 287` — `animator` field is declared on
  `EnemyBase` as `[SerializeField] protected CharacterAnimator animator`,
  so the calls land on `CharacterAnimator.SetAnimation`.
- Method definition itself at `CharacterAnimator.cs:22`.

**UnityEvent listeners:** I checked `m_MethodName: SetAnimation` across
all scenes and prefabs — no matches. **No UnityEvent wiring breaks.**

Total: 8 code callers + 1 definition = 9 places to update; 0 scene-side
breakage.

**Confidence:** high. The UnityEvent check was conservative — I assumed
nothing else in YAML would call `SetAnimation`.
