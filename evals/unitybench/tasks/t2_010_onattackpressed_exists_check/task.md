# Task: document the UnityEvent signature contract on OnAttackPressed

Add a comment above `PlayerController.OnAttackPressed` explaining that this
method's signature (public, no arguments, void return) MUST be preserved
because a UnityEvent listener in the scene calls it. Name the specific
scene GameObject that calls it.
