# Task: add a comment computing the real hits-to-kill count

Add a comment above `EnemyAI`'s `_damagePerHit` field that states how
many hits it takes to kill the Player in the current scene. The answer
depends on:

- The Player GameObject's `HealthSystem._maxHealth` Inspector value
- The scene Enemy's `EnemyAI._damagePerHit` Inspector value

Compute the ratio (round up) and put the actual number in the comment.
Use the real values that ship in the scene, not the code defaults.
