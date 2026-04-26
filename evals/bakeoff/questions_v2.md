# Bake-off v2 — 16-question expanded set

Original 8 questions kept. 8 new ones added below, chosen to stress
UnityGraph in places where it might be weaker than baseline grep:
properties, partial classes, generic types, async, extension methods,
interface impls, namespace collisions.

## NEW Tier 1/2 (adversarial — baseline should win or tie)

### Q9 — Property vs field (Tier 1)
"Does the script `EnemyBase` declare a property called `Health`, or just a
field? What's the exact line?"
*UnityGraph stores fields, not properties. If EnemyBase has a property,
UnityGraph will say "no field" — which is technically correct but
misleading for a refactor question.*

### Q10 — Generic type usage (Tier 2)
"Find every `List<T>` declaration where T is a user-defined class (not
Unity built-in). Return the script name and field/variable name."
*UnityGraph stores type names as strings. If it captured `List<EnemyBase>`
as a single string, it can answer; if it stripped the generic, it can't.*

### Q11 — Async/Task method count (Tier 1)
"How many methods in the project return `Task` or `async Task` / `async void`?
List them by class.name."
*UnityGraph's MethodInfo records name + lifecycle, but does it know
the return type? If not, this is grep-only.*

### Q12 — Interface implementations (Tier 2)
"List every user script that implements `IPointerClickHandler`."
*UnityGraph stores interfaces[] on each ClassInfo. Should be a one-query
answer. Baseline needs to grep for `: IPointerClickHandler` and walk
inheritance.*

## NEW Tier 3/4 (scene-code gap — UnityGraph should win)

### Q13 — Cross-scene script attachment count (Tier 3)
"How many distinct scenes/prefabs reference the script `<top singleton>`,
and which scenes/prefabs?"
*Source-only literally cannot answer "which scenes reference X" without
a guid index. UnityGraph's `who_uses` gives this with sites.*

### Q14 — Inspector override breadth (Tier 3)
"How many distinct serialized fields in the project have at least one
Inspector override (scene value differs from code default)?"
*A whole-project aggregate question. Baseline would need to walk every
.unity / .prefab and cross-reference. UnityGraph should answer in one
query loop.*

### Q15 — Refactor blast radius across inheritance (Tier 4)
"Every subclass of `<some user base class>` — list them and any methods
they override. Then for each, list scripts that depend on them."
*Multi-step refactor question that needs both inheritance traversal and
who_uses. UnityGraph should win decisively if the inheritance fix from
v2.1.2 is solid.*

### Q16 — Hidden coupling (Tier 4)
"Are there scripts that *reference* a script via a string-based lookup
(SendMessage, BroadcastMessage, Invoke) rather than a typed call? List
the source and the target method name."
*UnityGraph doesn't track string-based dispatch. Baseline grep can find
these. Tests honesty: does UnityGraph admit it doesn't know, or guess?*
