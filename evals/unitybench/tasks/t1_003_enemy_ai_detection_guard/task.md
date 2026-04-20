# Task: guard EnemyAI against missing player

In `EnemyAI.Start`, if `GameObject.FindWithTag("Player")` returns null, log
a warning via `Debug.LogWarning` explaining that the Player tag is missing
so the enemy will never activate. Keep the existing null-guard on
`_playerTransform` in `Update` intact.
