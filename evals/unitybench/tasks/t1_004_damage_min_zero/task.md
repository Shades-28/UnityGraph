# Task: ignore negative damage amounts

`HealthSystem.TakeDamage` currently accepts a negative `amount`, which
would heal the player because of how the `Mathf.Max` clamp works. Make
`TakeDamage` a no-op when `amount <= 0` — don't change `_current`, don't
invoke `_onDamaged`.
