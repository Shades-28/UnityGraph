# Task: make OnAttackPressed log which GameObject fired it

Modify `PlayerController.OnAttackPressed` to log an info message that
mentions the scene GameObject wired to fire this event. The goal is that
when the UI button is clicked, the log reads like
"Attack pressed (fired by UI_Button)" — referencing the actual scene
GameObject that invokes it.

Don't change anything outside the body of `OnAttackPressed`. You don't
need to pass the sender as an argument — hardcoding the source name is
acceptable since the scene wiring is fixed.
