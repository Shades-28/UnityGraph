# Scene-Code Gap Evidence — measured, not hand-waved

**Date:** 2026-04-23
**Method:** `evals/audit/scene_code_gap.py` — reads pre-built `graph.json` files for four Unity projects and counts facts that are present in scene/prefab YAML but invisible to a pure-C#-source reader.

## The finding

Real Unity projects contain **hundreds to tens of thousands** of facts hidden in scene/prefab YAML that a code-only AI cannot see. The gap scales with project size.

| Project | Nodes | Edges | Inspector overrides | UnityEvent wirings | Script attachments | Scripts in >1 scope |
|---|---:|---:|---:|---:|---:|---:|
| MiniUnityProject (fixture) | 26 | 41 | **4** | 1 | 5 | 1 |
| Indian-Bike-Gangster-3D | 1,335 | 1,755 | **67** | 2 | 289 | 29 |
| clash.io | 6,273 | 7,742 | **720** | 135 | 1,393 | 38 |
| Graudation-Saga | 72,564 | 98,916 | **15,321** | 472 | 10,680 | 194 |

## What the numbers mean

**Inspector override** — a serialized `[SerializeField]` (or public) field whose value on a specific scene/prefab instance differs from the C# code default. The code says `_speed = 5.0f`; the scene says `_speed = 7.0`. An AI reading only `.cs` files will reason from 5.0 and be wrong about the runtime.

**UnityEvent wiring** — a `subscribes_to` edge. These exist only in scene YAML's `m_PersistentCalls` block. There is no C# code anywhere that registers the listener — it was registered by dragging in the Inspector. An AI cannot see these at all from source.

**Script attachment** — the fact that a given `MonoBehaviour` is attached to a specific GameObject in a specific scene. Source tells you the script exists; only scene YAML tells you which scenes and prefabs actually use it.

**Scripts in >1 scope** — how many scripts are multi-instance. `ETFXProjectileScript` in Graudation-Saga is attached in 106 separate scenes/prefabs. "Where is this used?" is unanswerable from source.

## Concrete examples from the audit

**MiniUnityProject (the fixture, hand-authored by me):**
```
PlayerController._speed:  code=5.0f   scene=7.0   (on Player in Main.unity)
HealthSystem._maxHealth:  code=100    scene=150   (on Player in Main.unity)
EnemyAI._detectionRange:  code=10.0f  scene=12.0  (on Enemy in Main.unity)
EnemyAI._damagePerHit:    code=10     scene=15    (on Enemy in Main.unity)
```
This is the headline bug: the divisor in `HandleDamaged` should scale with `_speed`, not the literal `5.0f`. Detectable only because we surface the Inspector override.

**clash.io (real open-source Unity project, 1,393 script attachments):**
```
MMTouchButton.PressedChangeColor:   code=false   scene=1     (on Button3)
MMTouchButton.LerpColor:            code=true    scene=1     (on Button3)
MMTouchButton.LerpColorDuration:    code=0.2f    scene=0.1   (on Button3)
```
One button has seven fields overridden via Inspector. An AI refactoring `MMTouchButton` without seeing these would assume all defaults and silently break the demo scene.

**Graudation-Saga (real large project, 15,321 overrides, 472 UnityEvent wirings):**
```
SplineComputer.multithreaded:   code=false            scene=0     (on Paths)
SplineComputer.updateMode:      code=UpdateMode.Update scene=0    (on Paths)
SplineComputer._is2D:           code=false            scene=0     (on Paths)
SplineComputer.hasSamples:      code=false            scene=1     (on Paths)
```
A single `Paths` GameObject has 6+ `SplineComputer` fields overridden. `ETFXProjectileScript` is used in **106 scenes** — ask any AI "where is this used" without scene parsing and you get nothing useful.

## What this proves

✅ **The scene-code gap is real, at scale, and measurable without an LLM.**
✅ **Every hidden fact we listed is extractable from scene YAML.**
✅ **UnityGraph's `graph.json` already exposes every one of these facts to any MCP-aware agent.**

## What this does *not* prove (yet)

❓ **How often Claude actually gives a wrong answer when asked a Unity task without the graph.** The *opportunities* for wrongness are 720 in clash.io, 15k in Graudation-Saga. The realized error rate requires a controlled benchmark (UnityBench against a real Claude API).

## Honest limitations surfaced by the audit

- **67,709 "untracked Inspector values" in Graudation-Saga.** These are Inspector-set values on fields where our C# parser didn't capture a code default — usually because the script is from an asset-store package (TextMeshPro, NiceVibrations, Spline, etc.) whose source we didn't parse. Our graph still surfaces the *value*, just without the override-detection annotation.
- **Zero prefab variants detected in Graudation-Saga.** Could be genuine (flat prefab structure) or a parser miss. Worth investigating in v2.
- **`HealthSystem._maxHealth: scene=150` is wrong in the fixture table.** Actually the audit printed code=100, scene=150 — that's correct data, but note the fixture comment said the Inspector value was 150. Consistent with scene YAML and fixture README.

## Why this matters for v2

v2 adds **source evidence to every edge** (`sites[]` with file, line, snippet, kind, confidence). These audit numbers are the *breadth* proof — the gap exists. v2's `sites[]` is the *depth* proof — for every fact the graph exposes, here's exactly where in the project it came from. Together: a middleware that tells any AI agent "here is what your code files don't show you, and here's line-and-file provenance for every claim."

No LLM in our stack. No chat. Just pre-computed truth that any MCP-aware agent can query in one call instead of reading 50 files.
