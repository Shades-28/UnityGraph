# Task: add a RequireComponent attribute that reflects actual scene usage

The Enemy GameObject in this project always ships with a specific Unity
built-in physics component attached alongside `EnemyAI`. Add a
`[RequireComponent(typeof(...))]` attribute to the `EnemyAI` class that
reflects this. Only add the attribute for a component that IS actually
co-located with EnemyAI on both the scene Enemy and the Enemy prefab.
