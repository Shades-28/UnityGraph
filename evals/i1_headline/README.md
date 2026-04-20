# I1 Headline Test — *Speed-Proportional Slow*

## The bug

In `fixtures/MiniUnityProject`:

- `PlayerController._speed` is declared `5.0f` in the C# source.
- In `Main.unity`, the Inspector override on the `Player` GameObject sets
  `_speed = 7.0`.
- `PlayerController.HandleDamaged(int amount)` applies a slow:

  ```csharp
  _speedMultiplier = Mathf.Max(0.1f, 1.0f - (amount / 5.0f));
  ```

  The divisor `5.0f` is the **code default** max speed. At runtime the
  actual max is `7.0`, so the slow effect is proportionally wrong.

## The task

> Make the slow effect proportional to actual player speed.

## Without the graph (baseline)

Claude reads `_speed = 5.0f` from code, sees the divisor `5.0f` matches the
field default, and concludes the math is already correct — or makes a
symbolic change that doesn't fix runtime behavior. **The fix is wrong.**

## With UnityGraph (the fix Claude arrives at)

1. Claude calls `get_components(gameobject_name="Player")` → sees
   `PlayerController`, `HealthSystem`, `Rigidbody`, `CapsuleCollider`,
   `Transform`.
2. Claude calls `get_inspector_values(component_name="PlayerController",
   gameobject_name="Player")`.
3. The tool returns:

   ```json
   {
     "found": true,
     "matches": [{
       "inspector_values": {"_speed": 7.0, "_jumpForce": 8.0, "_maxHealth": 100},
       "code_defaults": {"_speed": "5.0f", "_jumpForce": "8.0f", "_maxHealth": "100"},
       "overrides": [{"field": "_speed", "inspector_value": 7.0, "code_default": "5.0f"}]
     }]
   }
   ```

4. Claude sees `_speed` is overridden to `7.0` and the slow's divisor is a
   hardcoded `5.0f` — a code-default assumption. The correct fix is to use
   the runtime field, not a literal.

## The correct patch

```diff
  private void HandleDamaged(int amount)
  {
-     _speedMultiplier = Mathf.Max(0.1f, 1.0f - (amount / 5.0f));
+     _speedMultiplier = Mathf.Max(0.1f, 1.0f - (amount / _speed));
  }
```

## Reproducing the evidence

```
unitygraph build fixtures/MiniUnityProject
python -m pytest tests/integration/test_mcp_server.py -v
python evals/i1_headline/record.py
```

`record.py` replays the same tool sequence a Claude Code session would use,
asserts the data needed to arrive at the correct fix is present, and writes
a machine-readable transcript to `evals/i1_headline/transcript.json`.
