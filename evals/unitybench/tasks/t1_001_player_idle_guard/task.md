# Task: skip Update movement when no input

In `PlayerController.Update()`, if both `Horizontal` and `Vertical` axes
are exactly 0, early-return so we don't call `AddForce` with a zero vector
on every frame. Everything else in `Update` should stay the same.
