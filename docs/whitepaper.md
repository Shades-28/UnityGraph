# UnityGraph: Closing the Scene-Code Gap for AI Coding Agents in Unity

A technical writeup of UnityGraph -- what problem it solves, how it
solves it, and a measured comparison against baseline file tools across
three real-world Unity projects.

---

## The problem

AI coding agents (Claude Code, Cursor, Aider, Copilot Workspace, and
similar) are good at reading C# source. They are bad at reading Unity
scenes. This is not a UI failing -- the scene data simply isn't in the
files the agent looks at.

Consider a typical Unity script:

```csharp
public class PlayerController : MonoBehaviour {
    [SerializeField] private float _speed = 5.0f;

    private void HandleDamaged(int amount) {
        _speedMultiplier = Mathf.Max(0.1f, 1.0f - (amount / 5.0f));
    }
}
```

The agent reads `_speed = 5.0f`, sees the `5.0f` literal in
`HandleDamaged`, and concludes the math is fine. But the developer set
`_speed = 7.0` in the Inspector on the actual `Player` GameObject. That
override lives in `Assets/Scenes/Main.unity` as YAML:

```yaml
PlayerController:
  m_Script: {fileID: 11500000, guid: ..., type: 3}
  _speed: 7.0
```

The agent never opens the scene file. Even if it did, it would have to
parse Unity's custom `!u!` YAML tags, resolve script GUIDs to .cs
files, and reason about prefab variants and override stacks. That's
doable in principle, but it's expensive (hundreds of file reads and
greps per refactor question) and few agents bother.

The same gap exists for several other facts that are scene-only:

* **UnityEvent listeners.** Click a button in the editor, drag a
  GameObject onto its `OnClick` slot, pick a method from a dropdown.
  That listener exists nowhere in code. It's a string in
  `m_PersistentCalls`. Renaming the target method in C# silently
  breaks the binding at runtime.
* **Prefab variant overrides.** A prefab variant sets `maxHealth = 150`
  on top of its parent's `maxHealth = 100`. The agent reads the parent.
* **Cross-scene script attachment counts.** "Where is `EnemyAI` used?"
  requires walking every `.unity` and `.prefab` file. Source can't tell
  you the answer.
* **Missing/broken script references.** A scene/prefab with
  `m_Script: {guid: <stale>}` is a "Missing (Mono Script)" warning in
  the Editor. Source has no record at all.

We measured this gap empirically on three real projects and found, per
project size:

| Project size      | User scripts | Inspector overrides | UnityEvent wirings | Missing-script refs |
|-------------------|---:|---:|---:|---:|
| Small (`clash.io`)| 49 game scripts | ~700 | 135 | 15 |
| Medium            | 9 game scripts | n/a* | 0 | 70K+ broken refs† |
| Large             | 1,519 user scripts | **15,000+** | 470+ | 25+ |

\* The medium project's user-script count is small because most of its
scenes/prefabs reference *deleted* scripts -- which is itself the
finding. A code-only reader would never know.

† Each broken reference is a "Missing script" warning the developer
sees in the Editor and an AI agent never sees from source alone.

The gap is real, scales with project size, and consists of facts that
are *extractable* but currently *unextracted* by every AI agent we know
of.

---

## The approach

UnityGraph is middleware. It does one thing: parse a Unity project into
a JSON graph and expose that graph through MCP (the Model Context
Protocol used by Claude Code, Cursor, and others).

```
Unity project          UnityGraph (offline)        AI agent (Claude Code, Cursor, ...)

.cs files       \
.unity scenes    >--> parsers --> graph.json --> MCP server --> tool calls
.prefab files   /

                       (runs locally)              (existing tooling)
```

Three principles guide the design:

### 1. No LLM inside UnityGraph.

We do not chat. We do not run inference. We do not call OpenAI or
Anthropic. The agent the developer is already using -- Claude Code,
Cursor, whatever -- does the reasoning. UnityGraph's job is to be the
pre-computed source of truth that any MCP-aware agent can query in
sub-50 ms. This makes us:

- **Agent-agnostic** -- works with any MCP client.
- **Free of model drift** -- every agent improvement helps us.
- **Cheap** -- no token cost, no latency we control.
- **Long-lived** -- middleware outlasts the chatbot category.

### 2. Every fact is traceable to source.

Every code-derived edge in the graph carries an array of *evidence
sites*. A site records:

```json
{
  "file": "Assets/_Assets/Scripts/Enemy/EnemyController.cs",
  "line": 80,
  "col": 13,
  "kind": "get_component",
  "snippet": "enemy.GetComponent<EnemyBase>()",
  "containing_method": "SpawnEnemy"
}
```

This is the [Roslyn `ReferenceLocation`](https://learn.microsoft.com/en-us/dotnet/api/microsoft.codeanalysis.findsymbols.referencelocation)
shape applied to a Unity-aware graph: one logical edge can carry many
evidence sites, each pointing at a distinct file+line where the
relationship is observable. A "rename impact" answer is no longer a
list of class names -- it's a list of file:line:snippet click-throughs.

On a real project with 1,519 user scripts, this layer materializes
~27,000 clickable evidence sites across `depends_on`, `attached_to`,
`subscribes_to`, `inherits`, `prefab_override`, and `method_call`
edges.

### 3. Honest about what it cannot do.

UnityGraph stores call sites, not method bodies. It tracks field types
(walking inheritance chains), not C# property getters that look like
fields. It records UnityEvent listener bindings (which live as strings
in scene YAML), but ignores `SendMessage`/`Invoke` runtime dispatch
because those targets are also strings, only at *runtime*, with no
reliable static signal.

When the agent asks a question UnityGraph can't answer, it returns
"this isn't in the graph" rather than guessing. An agent combining
UnityGraph queries + ordinary file tools is strictly better than either
alone -- UnityGraph short-circuits the cross-asset queries that cost a
file-tool agent 50+ greps; the file tools handle the source-level
reasoning UnityGraph deliberately does not.

---

## What's in the graph

### Node types

`Script`, `GameObject`, `Component`, `Scene`, `Prefab`,
`AnimatorController`, `AnimState`, `ShaderGraph`.

### Edge types

`attached_to`, `co_exists_with`, `depends_on`, `inherits`,
`subscribes_to` (UnityEvent listeners), `is_variant_of`, `overrides`
(prefab field overrides), `transitions_to` (animator), `loads_scene`,
`contains_state`, `has_animator`, `uses_subgraph`.

### Evidence-site kinds

`get_component`, `find_object`, `method_call`, `field_decl`,
`inherits`, `implements`, `subscribes_to`, `inspector_override`,
`prefab_override`, `transitions_to`, `attached_to`.

### MCP tools exposed (17)

Direct lookups (legacy, schema 1.x):
`get_components`, `get_inspector_values`, `get_event_connections`,
`get_scene_graph`, `get_prefab_chain`, `find_script_usages`,
`get_neighbors`, `shortest_path`, `query_graph`,
`inject_context` (Layer 2).

Refactor-planning queries (added in v1.6, evidence-rich):
`who_uses`, `impact_of`, `find_singletons`,
`inspector_overrides_for`, `field_wiring`, `event_listeners`,
`find_missing_scripts`.

---

## Evaluation: bake-off vs baseline file tools

To measure whether UnityGraph actually helps, we ran a head-to-head
comparison: same questions, same project, same agent, two tool sets.

### Setup

* **Baseline configuration**: agent has `Read`, `Glob`, `Grep` only.
  The standard tool set every modern AI coding agent has.
* **UnityGraph configuration**: same three tools + the MCP query
  library above.
* **Three projects**: a small open-source Unity game (`clash.io`,
  ~6,000 nodes), a medium broken-prefab project, and a large
  production project (~73,000 nodes). The latter two are anonymized.
* **16 questions on the small project**, 7 focused questions on each
  larger project.
* **Question tiers**:
  - Tier 1: pure-code questions answerable by reading one .cs file.
    Expect baseline to win or tie.
  - Tier 2: cross-file structural questions answerable by grep.
    Expect ties, with UnityGraph slightly cleaner (pre-filters
    comments, strings).
  - Tier 3: scene-code-gap questions. UnityGraph should win.
  - Tier 4: refactor-planning synthesis. UnityGraph should win on
    completeness; baseline answers exist but require many tool calls.

Every answer was scored against ground truth verified directly from
source/scene/prefab files, not from UnityGraph itself (avoiding
circularity).

### Headline result

| Project size | Baseline ✅ | UnityGraph ✅ | Net    |
|---|---|---|---|
| Small | 13 / 16  | 14 / 16   | UG wins 3, baseline wins 2, 11 ties |
| Medium | 4 / 7   | 7 / 7     | UG wins on Q7 ("missing scripts") others tie |
| Large  | 4 / 7    | 7 / 7     | UG wins 5/7 decisively |

Across all three projects: ~9 outright UnityGraph wins, 2 outright
baseline wins, the rest ties.

### Where UnityGraph wins (and why)

**Q5 -- Inspector overrides on the largest singleton.** On the large
project, a single user script (`SplineComputer`-equivalent) has 6,660
scalar Inspector overrides distributed across 1,110 attachments in 14
distinct scopes. Baseline's grep workflow needs hundreds of tool
calls; UnityGraph's `inspector_overrides_for` returns the answer in
~20 ms. **UnityGraph wins decisively.**

**Q7 -- Missing-script references.** A common Unity-project hygiene
question. On the large project, 25 distinct script GUIDs are
referenced by scenes/prefabs but resolve to no `.cs` file. Baseline
needs to enumerate ~611 distinct GUIDs in scenes/prefabs and
cross-reference against ~1,520 `.cs.meta` files. Theoretically
possible, conversationally infeasible. UnityGraph's
`find_missing_scripts` returns the answer in one call. **All three
projects, decisive.**

**Q8 -- Cross-inheritance refactor impact.** The bake-off's hardest
single test. "Rename `CharacterAnimator.SetAnimation`. What breaks?"
Ground truth: 8 callers across two classes (`CharacterBehaviour`'s 4
direct calls, `EnemyMelee`'s 4 calls on the *inherited* `animator`
field declared on `EnemyBase`). Initial UnityGraph implementation
returned 4 (it parsed each .cs file in isolation, missing the
inherited-field receiver). After implementing
inheritance-chain field resolution at builder time -- visiting each
class's ancestry to look up unresolved member-call receivers -- it
returns the full 8. **A real product bug found by the bake-off, then
fixed.**

### Where baseline wins (and why)

**Q1 -- "What does method X do?"** UnityGraph stores call sites, not
method bodies. The graph correctly says "SpawnEnemy is at line 74,
calls GetComponent<EnemyBase>". For a one-sentence summary of what
the method does, you still want the source. **Scope decision, not
bug.**

**Q11 -- "Which methods are async?"** UnityGraph's `MethodInfo`
records name + line + lifecycle, not return type. Baseline grep finds
async methods trivially. **Scope decision -- async return tracking
would expand the schema by 10% for a feature only one query needs.**

**Q16 -- "Which scripts use `SendMessage('Foo')`?"** String-based
runtime dispatch is invisible to a structural graph by design.
Baseline grep wins. **Honest limit.**

### What ties tell us

On the small project, most questions tie. Both runs converge on
correct answers because the search surface is small enough that grep
is fast. **UnityGraph's product value is project-size-dependent**:
the win condition is "at scale, cross-asset queries that cost
baseline 50+ tool calls cost UnityGraph 1." On a tutorial project,
baseline is fine. On a real game, the asymmetry compounds.

The medium project illustrates a different story: only 9 user scripts
but 70,000+ broken prefab references. Source-only readers see a
mostly-empty `Assets/Scripts/`. UnityGraph's `find_missing_scripts`
surfaces "this project is fundamentally broken" in one call.

---

## Architecture in a paragraph

C# source is parsed with [tree-sitter](https://tree-sitter.github.io/),
producing class info, field declarations with types, method
declarations, and call sites with file/line/col. Unity YAML scenes and
prefabs are parsed with PyYAML using a custom regex pre-processor for
Unity's `!u!classID &fileID` document headers. `.controller` and
`.shadergraph` files have their own structural parsers. The builder
runs all parsers, builds a guid->file index from `.meta` files
(skipping `Library/PackageCache/` to avoid leaking Unity's bundled
package code), threads inheritance chains for cross-class field
resolution, and emits a single `graph.json`. The MCP server is a thin
stdio wrapper over a deterministic query library; the Observatory web
UI is a stdlib HTTP server + a small force-graph frontend that streams
SSE updates when the project rebuilds. The whole thing is Python
3.11+, MIT-licensed, ~8K lines of code, 187 tests.

---

## Limits, by design

* **No method bodies.** UnityGraph stores call sites; for "what does
  this method do?" point your agent at the file:line.
* **No return types.** Methods record name + line + lifecycle, not
  `async Task` / `Task<T>`.
* **No string-based runtime dispatch.** `SendMessage("Foo")` is
  invisible -- the target is a string literal at runtime, not a typed
  call.
* **Properties are partially tracked.** Field-typed receivers resolve
  through the inheritance chain; property getters that look like
  fields are best-effort.
* **No reflection / IL inspection.** If the project relies on
  `Assembly.GetType(...)` or `gameObject.AddComponent(Type.GetType(...))`,
  the call won't appear in the graph.

These are scope decisions, documented as such, surfaced in the agent's
own answers when asked questions outside that scope. An agent that
combines UnityGraph + file tools will route around the limits
naturally.

---

## Related work

* **[Roslyn](https://github.com/dotnet/roslyn)** -- our `sites[]`
  schema is a direct adaptation of Roslyn's
  `ReferenceLocation`. We chose tree-sitter over Roslyn for parser
  flexibility (Unity scenes are not C# source).
* **[CodeQL](https://codeql.github.com/)** -- the prior art for
  database-style code queries. UnityGraph is far less ambitious in
  query expressiveness but adds the Unity-specific scene/prefab
  layer that CodeQL doesn't model.
* **[tree-sitter](https://tree-sitter.github.io/)** -- the parser
  generator powering our C# extraction.
* **[MCP](https://spec.modelcontextprotocol.io/)** -- the protocol
  that lets us be agent-agnostic. UnityGraph is one of the early
  MCP servers focused on a single domain rather than a cloud
  service.
* **Code property graphs** (Yamaguchi et al., *Modeling and
  Discovering Vulnerabilities with Code Property Graphs*, S&P 2014) --
  the schema lineage UnityGraph descends from. The principle that
  edges should carry source-level evidence comes from this line of
  work.

What's distinct about UnityGraph: the *Unity scene* is a first-class
data source. None of the above tools model the gap between code and
Inspector values, between code and prefab variants, between code and
runtime UnityEvent wiring. That gap is the whole product.

---

## Status and roadmap

UnityGraph 2.1.3 is shipping today on PyPI. The 17 MCP tools are
stable. The bake-off harness is reproducible and committed
(`evals/bakeoff/`). 187 tests pass on Windows + Python 3.12; macOS
and Linux are best-effort (the test suite runs, the code is
platform-agnostic, but I have not yet tested the
installer on those platforms).

Open work, ranked by priority:

1. **First-user feedback.** macOS install path is unverified.
   Property-receiver resolution gaps will surface on real projects we
   haven't tested yet. Expect a fast-follow patch release.
2. **Async / Task return types** (closes Q11) -- ~30 lines in
   `cs_parser.py`, add to `MethodInfo` schema.
3. **Native Unity package** (UPM) wrapper -- a `.unitypackage` that
   bundles the Python binary and exposes a small Editor window.
   Removes the "you need Python" friction for Unity devs.
4. **Reflection-edge inference** -- when a class extends a known base
   that has serialization, model the implied `instantiates` edges.
   Speculative; only worth it if real users ask.

The repo is at <https://github.com/Shades-28/UnityGraph>. Issues and
PRs welcome.
