# UnityGraph v2 — The Evidence Layer

**Status:** Approved (scope tightened per user direction 2026-04-23).
**Supersedes:** `2026-04-23-explanation-layer-design.md` — same foundations, stricter scope.
**Principle:** UnityGraph is middleware. It does not chat. It does not reason. It does not call an LLM internally. It makes Unity projects queryable for any AI agent.

---

## 1. One-sentence spec

Enrich the graph so every edge carries source-level evidence (`sites[]`), add a deterministic query library, expose both through MCP. No chatbot. No inference. No LLM inside UnityGraph.

## 2. The problem this solves (measured, not asserted)

From `docs/findings/2026-04-23-scene-code-gap-evidence.md`:

- Real Unity projects contain **15,321 Inspector overrides** (Graudation-Saga), **720** (clash.io), **67** (Indian-Bike-Gangster-3D).
- Real Unity projects contain **472 UnityEvent wirings** (Graudation-Saga), **135** (clash.io) — facts that exist only in scene YAML, invisible in C# source.
- Scripts can be attached in **100+ scenes** (`ETFXProjectileScript` in Graudation-Saga appears in 106 scopes).

Each of these is a fact a code-only AI agent cannot see. v1 exposed the counts; v2 makes every fact traceable to a source location (`file, line, snippet`).

## 3. Product position — why middleware, not product

- **Agent-agnostic.** We work with Claude Code, Cursor, Windsurf, Aider, Copilot — any tool that speaks MCP. We never ship an LLM.
- **No model drift.** Every agent improvement becomes our improvement for free.
- **No token bill, no latency we control.** Tool calls are <50ms; the agent's own LLM pays the latency of reasoning.
- **Single responsibility.** Do one thing well: parse Unity → serve a rich queryable graph.
- **Long-lived.** Middleware outlasts chatbots. We are infrastructure, not a product category.

Explicitly out of scope: any `unitygraph ask`, any `explain(task_text)` that calls an LLM, any chatbot UI. The agent does the talking; we hand it the facts.

## 4. Schema v2.0 — the hard changes

### 4.1 Edges carry `sites[]`

```jsonc
{
  "from": "script::PlayerController::Assets/Scripts/PlayerController.cs",
  "to":   "<resolved target>",
  "type": "depends_on",
  "sites": [
    {
      "file": "Assets/Scripts/PlayerController.cs",
      "line": 22,
      "col":  13,
      "end_line": 22,
      "end_col": 52,
      "snippet": "_rigidbody = GetComponent<Rigidbody>();",
      "kind": "get_component",
      "containing_method": "Awake",
      "confidence": "EXTRACTED"
    },
    {
      "file": "Assets/Scripts/PlayerController.cs",
      "line": 38,
      "col":  13,
      "snippet": "_rigidbody.AddForce(dir);",
      "kind": "method_call",
      "containing_method": "Update",
      "confidence": "EXTRACTED"
    }
  ]
}
```

**Shape follows Roslyn's `ReferencedSymbol` / `ReferenceLocation`** — one logical edge, many evidence sites. Storage cost: ~50 B per site, far cheaper than one edge per reference (as research confirmed — see `docs/findings/` if added later).

### 4.2 `kind` enum (what sort of evidence this site is)

| Kind | Where it fires |
|---|---|
| `get_component` | `GetComponent<T>()` / `TryGetComponent` |
| `find_object` | `FindObjectOfType<T>` / `FindObjectsOfType<T>` |
| `method_call` | any `x.Method()` where `x` is a field of the target type |
| `field_decl` | `[SerializeField] private T x;` |
| `inherits` | class declaration base list |
| `implements` | class declaration interface list |
| `instantiates` | `Instantiate(prefab)` |
| `subscribes_to` | `m_PersistentCalls.m_Calls[*]` in scene YAML |
| `inspector_override` | Inspector value where scene ≠ code default |
| `prefab_override` | `m_Modifications[*]` in `PrefabInstance` |
| `transitions_to` | `AnimatorStateTransition` |
| `require_component` | `[RequireComponent(typeof(T))]` |

### 4.3 `confidence` enum

- `EXTRACTED` — comes from deterministic AST / YAML parsing. No guessing.
- `INFERRED` — pattern-matched by a heuristic (e.g. "this looks like a singleton"). Not shipped in v2.0; reserved for v2.1+.
- `AMBIGUOUS` — matched a pattern but multiple candidate targets exist. Reserved.

**v2.0 only emits `EXTRACTED`.** Honest labels.

### 4.4 `Rationale` as a new node type

```jsonc
{
  "id": "rationale::docstring::Assets/Scripts/PlayerController.cs#L12",
  "type": "Rationale",
  "source": "xml_doc",          // xml_doc | inline_comment | todo
  "text": "Player movement and attack controller. The Inspector value of _speed overrides the code default.",
  "provenance": { "file": "Assets/Scripts/PlayerController.cs", "line": 12 }
}
```

Linked via new edge type `explains` pointing at whichever code node it justifies. **v2.0 harvests only from XML `<summary>` comments and inline `// WHY:` / `# WHY:` markers.** Git commit mining is v2.1+.

### 4.5 `schema_version` bump to `"2.0"`

Loader accepts v1.x graphs and synthesizes empty `sites: []` per edge so the Observatory + MCP tools don't break. Re-build required to get real sites.

## 5. The parser changes (the real engineering)

Tree-sitter already exposes `start_point` / `end_point` on every node. We stop discarding them.

### 5.1 `cs_parser.py`

Today: `get_component_types: list[str]` → `["Rigidbody", "HealthSystem"]`.
Tomorrow: `get_component_calls: list[GetComponentCall]` where:

```python
@dataclass
class GetComponentCall:
    type_arg: str             # "Rigidbody"
    method: str               # "GetComponent" | "TryGetComponent"
    line: int
    col: int
    end_line: int
    end_col: int
    snippet: str              # "_rigidbody = GetComponent<Rigidbody>();"
    containing_method: str    # "Awake"
```

Same upgrade for `FindObjectOfType` calls. Method calls on stored fields (`_rigidbody.AddForce(...)`) get a new `field_method_calls` list with the same shape — this is how we know PC not only *stored* a Rigidbody but also *uses* it, which is stronger evidence of actual dependency.

### 5.2 `scene_parser.py`

Today: UnityEvent `m_Calls` are parsed but the YAML line number is thrown away when we hand the body to `yaml.safe_load`.
Tomorrow: a line-preserving YAML walker for the specific keys we need (`m_PersistentCalls`, `m_Modifications`, `m_Script`). We don't need full line tracking on every YAML key; just the ones we emit edges from.

Implementation: count `\n`s in the text up to the document match — `unity_yaml.load_documents` already has the regex index; we just add a helper that computes the line number for a byte offset and attach it to each emitted `EventConnection` / `PrefabOverride`.

### 5.3 `animator_parser.py`, `shadergraph_parser.py`

Same treatment — emit `line` alongside every state/transition/property extracted. Low-complexity.

### 5.4 `builder.py`

- When emitting an edge, package the parser-returned site tuple into the edge's `sites` list.
- De-dup on `(from, to, type)`: if the same edge would be emitted twice from two different sites, merge into one edge with both sites. (v1 emits duplicates today — this is a net improvement on its own.)
- Total change: ~150 lines.

## 6. The deterministic query library

`src/unitygraph/query/presets.py` — each preset is a function `(Graph) -> list[QueryHit]`:

### v2.0 preset catalog

1. `who_uses(script_name)` — every GameObject with this script attached, across scenes and prefabs.
2. `components_on(gameobject_name, scope=None)` — every component + Inspector values.
3. `inspector_overrides_for(script_name)` — every place this script has an Inspector value that diverges from code default. (The audit script was the prototype.)
4. `find_missing_scripts()` — every scene/prefab with a `MonoBehaviour` whose guid doesn't resolve (Unity's red "Missing Mono Script" state).
5. `find_hot_path_calls()` — every `GetComponent<T>` inside `Update` / `FixedUpdate` / `LateUpdate` (perf smell).
6. `find_object_calls()` — every `GameObject.Find` / `FindObjectOfType<T>` (fragile pattern).
7. `find_singletons()` — classes with a `public static X Instance` pattern (heuristic-based, flagged as such).
8. `impact_of(node_id_or_name)` — reverse-BFS over edges from this node. "If I delete / rename this, what else breaks?"
9. `field_wiring(script_name, field_name)` — every scene/prefab value for one serialized field across the project.
10. `event_listeners(gameobject_name)` — complete outgoing + incoming UnityEvent wiring.

### v2.0 CLI

- `unitygraph query <preset> [args]` — table-formatted output, exits 0 or 1 based on "did it find anything?" (useful for CI gates).
- Each preset also gets a `--json` flag for scripting.

### v2.0 MCP tool surface

One MCP tool per preset. Names match the Python function names. Tools return structured JSON, never prose. **The agent decides how to present the answer.** We never explain; we never rank; we never reason about relevance.

Current MCP tool count: 10. After v2: ~20. Most <50ms.

## 7. Observatory changes (read-only viz; no chat)

- **Evidence popover** — click an edge, a small panel shows up to 5 sites with syntax-highlighted snippets, collapsible beyond that.
- **Confidence ribbons** — edges drawn with varying opacity by `confidence` (EXTRACTED = solid, INFERRED = dashed, AMBIGUOUS = dotted). Only `EXTRACTED` exists in v2.0; the styling future-proofs.
- **"Inspector overrides" toggle** — single button on the top-right that filters to `Script` nodes with ≥1 override. Designed for the "show me the scene-code gap" demo.
- No chat, no text box, no natural-language search → natural-language output path. Search remains a pure node-name filter.

## 8. Migration: v1 → v2 graphs

- Loader synthesizes `sites: []` for every v1 edge on read. Nothing breaks.
- MCP tools that depend on `sites` gracefully return an empty list with a note: `"sites_available": false`.
- Observatory shows "no evidence" in the popover for legacy edges.
- Full evidence only after `unitygraph build --update` with a v2-capable package.

## 9. Testing strategy

- **Schema conformance** — JSON Schema validation for v2 graphs in CI.
- **Roundtrip tests** — hand-authored `.cs` + `.unity` → expected edges + sites. Reuse MiniUnityProject.
- **Parser location tests** — for every `GetComponent<T>` in the fixture, assert the emitted site has the correct line and snippet.
- **Query correctness tests** — for each preset, at least one positive and one negative case against MiniUnityProject.
- **Roundtrip determinism** — build the same project twice, diff the graphs. Expected: zero diff except timestamps.
- **Performance** — clash.io build stays within 1.5× v1 build time. (Line capture is a fixed-cost per AST node; edge dedup is a net win on large graphs.)
- **Integration test for legacy v1 graphs** — load a v1 graph, verify MCP tools don't crash and return empty sites.

## 10. What v2.0 does NOT include (intentionally)

- ❌ `unitygraph ask` / `explain(task_text)` / any LLM-in-UnityGraph. Ever.
- ❌ Git commit message mining (v2.1+).
- ❌ Intent classification ("this is a singleton pattern") — only in `find_singletons` as a deterministic heuristic, not in the graph.
- ❌ Scene writes. Claude still cannot modify scenes through us. (Separate product shape, separate design.)
- ❌ Unity Editor plugin. (Desirable; separate workstream.)
- ❌ Cross-project / multi-graph federation.
- ❌ Anything that requires an external network call.

## 11. Success criteria — verifiable without an LLM

1. A `depends_on` edge from `PlayerController` to `HealthSystem` exists with sites pointing at the `GetComponent<HealthSystem>()` call at `Awake` line ~22 *and* the `_health.OnDamaged.AddListener(...)` at `Start` line ~30.
2. `unitygraph query impact_of PlayerController` on clash.io completes in <100ms and returns 1-2 scenes.
3. `unitygraph query find_hot_path_calls` on Graudation-Saga returns a finite list (could be 0-20, not a scan error).
4. `unitygraph query inspector_overrides_for MMTouchButton` on clash.io returns ≥7 hits (matches the audit).
5. Observatory popover shows the snippet `_rigidbody = GetComponent<Rigidbody>();` when clicking the `PlayerController→Rigidbody` edge in MiniUnityProject.
6. Running v1 MCP tools against a v2 graph returns the same shape (no shape regression).
7. clash.io build time stays under 6s (v1 was 3.8s, budget is 6).

## 12. Rollout

1. Land `kind` enum + site dataclass in `build/graph.py`. Ship as v1.3.0 (no parser changes yet; empty sites).
2. Land location-aware `cs_parser`. Sites start appearing on code-side edges. Ship as v1.4.0.
3. Land location-aware `scene_parser` (YAML line tracking). Sites appear on scene-side edges. Ship as v1.5.0.
4. Land the query library + new MCP tools. Ship as v1.6.0.
5. Land the Observatory evidence popover. Ship as v2.0.0.
6. Mark schema `2.0`. Cut release.

Each step is incrementally shippable and self-contained. No "big bang."

## 13. What happens after v2

- **v2.1** — Git commit harvesting for `Rationale` nodes. Useful for "why was this value set this way?"
- **v2.2** — Unity Editor plugin that embeds the Observatory.
- **v3.0** — scene writes (UnityGraph becomes two-way, allowing agents to commit back scene changes via YAML patching). Separate design.

---

## Self-review

- **Placeholders:** none — every section has concrete claims.
- **Contradictions:** none found.
- **Ambiguity:** `confidence` values formalized (EXTRACTED / INFERRED / AMBIGUOUS); v2.0 only emits EXTRACTED.
- **Scope:** single coherent implementation plan. No LLM. No chatbot. Extends the pipeline we already own.
