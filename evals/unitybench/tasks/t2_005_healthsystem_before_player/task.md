# Task: add an explanatory comment about execution order

In `PlayerController.Awake`, the call to `GetComponent<HealthSystem>()`
will find an initialized HealthSystem on the same GameObject — but only
because of a specific execution-order configuration in this project. Add
a comment in `PlayerController.Awake` (above the GetComponent call) that
explains why it's safe to rely on HealthSystem being ready at this point.
Cite the execution order value.
