# UnityGraph v2 — The Explanation Layer

**Status:** Draft (awaiting approval)
**Date:** 2026-04-23
**Author:** collaboration with Aryan
**Based on:** three parallel research agents (tool landscape, schema prior-art, query taxonomy)

---

## 1. The problem

UnityGraph v1 answers **what** a Unity project contains. It doesn't answer **why**.

Concrete example: the graph knows `PlayerController --depends_on--> Rigidbody`. It doesn't know:

- That the dependency is because `PlayerController.Update()` line 38 calls `_rigidbody.AddForce()`.
- That the Inspector on the scene Player sets `_speed = 7.0` because this is the fast-movement variant.
- That `HealthSystem` runs before `PlayerController` because `MonoManager.asset` sets its execution order to -100 to ensure `_current` is initialized before any `GetComponent<HealthSystem>()` call in Awake.

The **why** is latent in the source — every "why" is reconstructible from a file + line + snippet — but our parsers throw away line numbers and call contexts. Consequence: a developer (or Claude) asking "why does PlayerController need Rigidbody?" gets either no answer or a confidently hallucinated one.

## 2. What the research tells us

Three agents ran in parallel. Their combined signal:

- **~50% of real Unity dev questions are deterministic and graph-only-answerable.** This is the Rider-style "find usages, list GameObjects with X, where is this field set" surface. No LLM. Queryable all day. *(Agent 3.)*
- **~35% need LLM reasoning on top of good graph data.** "Why does X need Y?" "Explain how input flows here." "What breaks if I delete this?" — the graph provides the facts, the LLM provides the prose. *(Agent 3.)*
- **The tools that win are queryable throughout the day.** Rider's Find Usages, Sourcegraph. **The tools that die do so because pretty visuals alone don't retain users** — CodeSee shut down in 2024 despite beautiful maps. *(Agent 1.)*
- **Roslyn has the right schema shape.** One logical edge with a `sites[]` array, each site carrying `{file, line, col, snippet, kind, reason}`. Cheaper than one-edge-per-reference, richer than LSP's just-a-location model. Rationale (commit messages, docstrings, TODO comments) live as separate `Rationale` nodes linked via `:EXPLAINS` edges. *(Agent 2.)*

## 3. Design principles

1. **Invest in deterministic queries first, LLM reasoning second.** Half the value ships without a model call. A shaky graph makes LLM reasoning hallucinate; a sharp graph makes it trustworthy.
2. **Every edge becomes explainable.** Each graph edge carries at least one *site* — a source location that justifies its existence. Edges without evidence are a bug.
3. **Sites are Roslyn-shaped.** `{file, line, col, snippet, kind, reason}`. Heterogeneous reasons allowed on one logical edge.
4. **Explanations over visualizations.** Every improvement must make a question *answerable*, not merely visible. Observatory stays as the glance-value surface; the real product is the query layer.
5. **Confidence labels on every site.** Steal Graphify's EXTRACTED / INFERRED / AMBIGUOUS tagging. An Inspector-value override is EXTRACTED. A guess that "`HealthSystem` exists because `PlayerController` assumes it" is INFERRED.

## 4. Schema changes — v1.1 → v2.0

### 4.1 Edges carry sites

```jsonc
// v1 (current)
{
  "from": "script::PlayerController::...",
  "to": "script::Rigidbody::...",      // or a concrete node
  "type": "depends_on",
  "via": "GetComponent",
  "target_type": "Rigidbody"
}

// v2 (new)
{
  "from": "script::PlayerController::...",
  "to": "<resolved Rigidbody node>",
  "type": "depends_on",
  "sites": [
    {
      "file": "Assets/Scripts/PlayerController.cs",
      "line": 22,
      "col": 13,
      "snippet": "_rigidbody = GetComponent<Rigidbody>();",
      "kind": "get_component",
      "containing_method": "Awake",
      "confidence": "EXTRACTED",
      "reason": null                    // optional human-readable; often null in extracted sites
    },
    {
      "file": "Assets/Scripts/PlayerController.cs",
      "line": 38,
      "col": 13,
      "snippet": "_rigidbody.AddForce(dir);",
      "kind": "method_call",
      "containing_method": "Update",
      "confidence": "EXTRACTED",
      "reason": null
    }
  ]
}
```

**Why sites[] and not separate edges:** per agent 2's research, four references = one edge + four 50B site entries (~200B) beats four full edges (~600B) and keeps traversal O(edges). It also lets us answer "give me one line about the PC→RB relationship" without collapsing the truth — the UI formatter picks the most informative site.

### 4.2 Rationale as a new node type

```jsonc
{
  "id": "rationale::commit::abc1234::player_speed",
  "type": "Rationale",
  "source": "git_commit",       // git_commit | docstring | todo | xml_doc | readme
  "text": "bumped speed to 7.0 — 5.0 felt too slow in playtest (issue #42)",
  "author": "aryan",
  "timestamp": "2026-03-14T12:00:00Z",
  "provenance": { "commit": "abc1234", "file": "Main.unity", "line": 127 }
}
```

Linked via a new edge type `EXPLAINS` pointing at whichever code node(s) it justifies. One rationale → many EXPLAINS edges (one commit can justify the values on 20 fields).

### 4.3 New edge kinds needed (minor additions)

| Edge type          | Why it's needed | Typical sites |
|---|---|---|
| `references`       | Catch-all for when a script mentions a type but the relationship isn't `depends_on` or `calls` | field decl, type arg |
| `field_wires_to`   | A scene-side `{fileID}` reference from one component's Inspector value to another object's MonoBehaviour | scene YAML line |
| `explains`         | Rationale → code | commit / comment |

### 4.4 Schema version bump

`schema_version: "2.0"`. Loaders handle v1.x by synthesizing empty `sites: []` for legacy edges so Observatory doesn't break.

## 5. Implementation shape

### 5.1 Parser changes (the real work)

Every parser becomes **location-aware**. Tree-sitter exposes `.start_point` (row, col) on every node — we just have to stop discarding it.

- **`cs_parser.py`** — Today: `get_component_types: list[str]`. Tomorrow: `get_component_calls: list[{type_arg, method, file, line, col, snippet, containing_method}]`. Similarly for `FindObjectOfType`, method calls on stored fields, etc.
- **`scene_parser.py`** — Today: UnityEvent persistent calls get `target_file_id` and `method_name`. Tomorrow: also the YAML line number of the `m_Calls:` entry. Currently we throw this away when we feed bodies to `yaml.safe_load`; we'd need a custom YAML walker that preserves line info, or a secondary regex scan that finds those specific keys.
- **`animator_parser.py`** / **`shadergraph_parser.py`** — add line-number capture where we emit edges.

This is **extend, don't rewrite**. The parsers produce more fields; the builder assembles them into `sites[]`.

### 5.2 Builder changes

- The builder's edge-emission code already knows which parser call produced each edge. It just needs to pass the site tuple through.
- De-duplication: when two sites produce the same `(from, to, type)` edge, merge into one edge with both sites. (The builder doesn't do this today — we emit one edge per site and live with duplicates.)
- Complexity stays roughly the same — maybe ~100 net lines.

### 5.3 Query layer — the new surface

A new module `src/unitygraph/query/`:

- `query.py` — a library of deterministic queries matching the Agent-3 list:
  - `who_uses(script_name)` — find all attachments across scenes/prefabs
  - `components_on(gameobject_name, scope=None)` — list components
  - `find_missing_scripts()` — returns every scene/prefab with a `<Missing (Mono Script)>` entry
  - `find_hot_path_calls()` — every `GetComponent` in `Update` (perf smell)
  - `find_singletons()` — static instance patterns
  - `find_find_object_calls()` — every `GameObject.Find` / `FindObjectOfType`
  - `impact_of(node_id)` — walks edges backward; returns everything that would break if this were deleted
  - `field_wiring(field_id)` — all scene-side values for one serialized field across the project
  - etc.
- `explain.py` — renders an edge + sites as a one-paragraph explanation ("PlayerController depends on Rigidbody because it's stored in the `_rigidbody` field assigned in `Awake()` at line 22, and used in `Update()` at line 38 to apply movement via `AddForce`.")
- `cli` additions:
  - `unitygraph query <preset>` — run a deterministic query
  - `unitygraph why <from> <to>` — explain why an edge exists (uses sites, no LLM)
- **MCP exposure** — every query becomes a tool: `impact_of`, `find_singletons`, `why`, `explain_edge`. Doubles our tool count, most of them cost <50ms.

### 5.4 LLM-augmented layer (scoped carefully)

One new MCP tool: `explain(task_text)`. It runs entity extraction, pulls the matching subgraph with sites, formats as a structured prompt, and asks Claude to write prose. **No new Claude-API dependency in the core package** — this is just a richer version of `inject_context`. Today's inject_context can absorb the enrichment for free; Claude already consumes the graph, now with sites.

Subjective questions ("is this architecture clean?") are **explicitly out of scope**. The CLI rejects them with a helpful message pointing at the deterministic queries.

### 5.5 Observatory surface changes

The viz detail card already has a template with typed rows. Add a **"Evidence" section** per edge — click any line in Component Relationships, a popover shows the sites with syntax-highlighted snippets. This is where "glance" becomes "query" in the same UI.

## 6. What we don't build (yet)

- **Git commit rationale mining.** Schema supports `Rationale` nodes, but the initial implementation only harvests XML doc comments and `# WHY:` / `// WHY:` inline comments. Commit-message harvesting is follow-up.
- **Intent-level semantic tags.** No "this is a singleton," "this is a service locator" classification. Heuristic queries can detect patterns, but we don't add an LLM classification pass.
- **Bidirectional write.** Claude still can't modify scenes. Tier 1 ergonomic gap, separate design.

## 7. Migration path

1. Land the parser changes behind a feature flag (`--schema v2` on build).
2. Emit v2 graph files at `schema_version: "2.0"`.
3. Observatory + MCP server accept both schemas; when v2 is available, show sites.
4. After a week of self-use on the three test projects (Indian-Bike, clash.io, Graudation-Saga), flip v2 to default.
5. Update UnityBench tasks to use v2 for richer task assembly.

## 8. Testing strategy

- **Schema conformance tests** — v2 parser output validated against a JSON Schema.
- **Roundtrip tests** — known source → expected sites. Reuse `fixtures/MiniUnityProject/` with hand-authored expected outputs for `PlayerController.Awake()` GetComponent calls.
- **Query correctness tests** — every new `query/` preset has at least one test against MiniUnityProject.
- **Explainability tests** — for every `depends_on` edge in MiniUnityProject, assert a human-readable explanation can be rendered from sites without an LLM.
- **Performance tests** — v2 build time on clash.io must stay within 1.5× v1 (additional line tracking has fixed overhead; edge dedup is a net win on large projects).

## 9. Success criteria

The Unity dev who triggered this design asks, unprompted, about their own project:

- *"What components does Player use?"* → deterministic query, <50ms, cites scene.
- *"Why does PlayerController need Rigidbody?"* → `unitygraph why PlayerController Rigidbody` → explanation with file+line snippets.
- *"What would break if I delete HealthSystem?"* → `unitygraph query impact_of HealthSystem` → lists every attachment, every method that calls it, every UnityEvent wired to its methods.
- *"Find every singleton / FindObjectOfType smell."* → `unitygraph query singletons` / `find_object_calls` → audit report.

If these four flows work, the explanation layer has closed the half of Unity-dev questions that are deterministic. LLM reasoning piggybacks on this foundation.

## 10. Open questions for you

1. **Rationale harvesting scope.** Initial pass: inline `// WHY:` + XML `<summary>` comments. Enough, or also Git commit messages in the first version?
2. **Query CLI shape.** `unitygraph query <preset> [args]` (what I sketched) vs `unitygraph where-used <name>` / `unitygraph impact <name>` (flat verb commands)?
3. **Observatory evidence popover — scope.** Show all sites, or cap at 5 and link to a "view all 23 references" page?
4. **Should `explain(task_text)` be an MCP tool at all in this pass?** Or should we keep v2 pure-deterministic and ship the LLM layer as v2.1?

---

## Self-review (after drafting)

**Placeholders:** none — every section has a concrete claim.
**Contradictions:** section 4.4 says legacy edges get synthetic empty `sites`; section 8 assumes v2 fixtures for tests. Both consistent — v2 fixtures are new, v1 fixtures get migrated on load.
**Ambiguity:** "confidence" enum values aren't formalized. Fixed: they are `EXTRACTED` (from AST / YAML, deterministic), `INFERRED` (our pattern detector guessed), `AMBIGUOUS` (matched a pattern but more than one plausible target).
**Scope:** one design doc → one implementation plan. The doc refuses Git commit harvesting, scene writes, LLM classification passes — all deferred. Good.
