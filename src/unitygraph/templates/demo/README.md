# MiniUnityProject -- I1 fixture

Hand-authored minimal Unity project used as the I1 headline-test fixture. Not generated from Unity Editor; YAML is hand-crafted to exercise the parsing paths UnityGraph's Layer 1 needs.

## What's inside

- **Scenes/Main.unity** -- 5 GameObjects: `Main Camera`, `Ground`, `Player`, `Enemy`, `UI_Button`
- **Scripts/** -- `PlayerController.cs`, `HealthSystem.cs`, `EnemyAI.cs`
- **Prefabs/Enemy.prefab** -- referenced from the scene, flat (no variants)
- **ProjectSettings/ScriptExecutionOrder.asset** -- forces `HealthSystem` to run before `PlayerController`

## The headline bug (I1 gate)

- `PlayerController._speed` code default = `5.0`, Inspector override on `Player` GameObject = `7.0`
- `HealthSystem` applies a slow effect assuming max speed is 5.0 -- wrong at runtime
- Task given to Claude with MCP: *"Make the slow effect proportional to actual player speed."*
- Correct solution requires calling `get_inspector_values("PlayerController", "Player")` and seeing `_speed = 7.0`

## Script GUIDs (stable)

Do not regenerate. The scene/prefab YAML references these:

| Script | GUID |
|---|---|
| PlayerController.cs | 11000000000000000000000000000001 |
| HealthSystem.cs     | 11000000000000000000000000000002 |
| EnemyAI.cs          | 11000000000000000000000000000003 |

FileIDs for MonoScripts in Unity are conventionally `11500000`.
