# Task: cache the distance-squared calculation

In `EnemyAI.Update`, replace the `Vector3.Distance` call with a
`(transform.position - _playerTransform.position).sqrMagnitude` comparison
against `_detectionRange * _detectionRange`. This avoids the sqrt every
frame.
