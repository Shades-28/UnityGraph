# Task: make the slow effect proportional to the actual player speed

`PlayerController.HandleDamaged` applies a slowdown when the player is hit.
The current math hard-codes a divisor that assumes a specific max speed.
The slowdown feels wrong at runtime — after a hit the player still moves
at a noticeable speed.

Make the slow proportional to the player's actual configured speed so the
effect scales correctly regardless of what `_speed` is set to.
