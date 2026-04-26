# Changelog

All notable changes to UnityGraph. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [SemVer](https://semver.org/).

## [2.1.3]

### Fixed
- `unitygraph init --demo .` against an empty existing directory used
  to crash with `FileExistsError` because `shutil.copytree` was called
  with `dirs_exist_ok=False`. The "exists and not empty" guard above
  it already prevents accidental clobbers, so the safe fix is to allow
  copytree into an empty target. New regression test in
  `tests/unit/test_init_command.py`.

## [2.1.2]

### Fixed
- C# parser now resolves method calls on **inherited fields**. Previously
  a subclass calling `inheritedField.Method(...)` was dropped because the
  parser only saw fields declared on the same class. Now the builder
  walks the inheritance chain after parsing every script and promotes
  unresolved member calls into `field_method_calls`. The bake-off Q8
  ("rename impact across inheritance") improved from 4 to 8 callers
  found on the test fixture.
- Cache invalidation: `PARSER_VERSION` 3 → 4 so cached graphs from
  v2.1.1 rebuild on first run.

### Added
- `evals/bakeoff/` -- runnable comparison harness contrasting baseline
  (Read/Glob/Grep) against UnityGraph on the same questions. 16 questions
  on a small project + 7 focused questions on two larger projects.
  Aggregate scorecard committed at `evals/bakeoff/AGGREGATE_SCORECARD.md`.
- 6 new unit tests for the inheritance fix in
  `tests/unit/test_inherited_field_resolution.py`.

## [2.1.1]

### Added
- **Observatory scope filter.** `/graph.json?scope=user` returns only
  user-script-related nodes (defaults to user-owned scripts + 1-hop
  neighbours). Brought a 1.1 GB graph.json down to 25 MB on a real
  large-project test, making the Observatory actually loadable.
- `?max_nodes=N` cap with `truncated: true` flag on the response.
- 4 new unit tests for `_filter_user_scope`.

### Changed
- Frontend defaults to scope=user; toggle in UI for full-graph view.

## [2.1.0]

### Fixed
- **Library/PackageCache leak in the guid index.** Real-project audit
  found `build_guid_index` was walking `Library/PackageCache/.../*.cs.meta`
  files. Scene references to Unity built-ins (Image, Button, TextMeshPro)
  resolved to `Library/` paths, dominating every "used everywhere" query.
  `find_singletons(>=5)` returned 29 entries on a real project where 28
  were Unity built-ins. After the fix it returns 2 -- the actual user-owned
  hot scripts.

### Added
- `_is_user_script` helper -- segment-based path classification (no
  substring false positives like "MyPluginsHelper.cs").
- `find_singletons` and `find_missing_scripts` gain `user_only` /
  `min_attachments` parameters (default to user-only / live-attachment).
- 15 new unit tests + 4 cross-project integration tests
  (`test_cross_project_site_validity.py`) sampling sites by kind to
  verify each points at real file content.

### Changed
- Cache `PARSER_VERSION` 2 → 3 so v2.0 graphs with Library-resolved
  placeholders rebuild cleanly.

## [2.0.0]

### Added -- schema 2.0, the evidence layer
- Every code-derived edge now carries a `sites[]` array with file, line,
  column, snippet, and kind. ~27,000 clickable evidence sites materialize
  on a typical large project.
- Observatory edge popover -- click any edge to see its evidence sites
  with kind badge, file:line, containing method, and source snippet.
- Schema bumped to "2.0". Loader still accepts v1.x graph.json files
  (empty sites[] on every edge) -- no break for users mid-upgrade.
- 7 new MCP tools: `who_uses`, `impact_of`, `find_singletons`,
  `inspector_overrides_for`, `field_wiring`, `event_listeners`,
  `find_missing_scripts`.

## [1.6.0] -- pre-2.0 build-up

Deterministic query library (`mcp/queries.py`) above the existing tools
layer. Pure-Python answers to "who uses X?", "what's the blast radius of
changing Y?", "which fields are tuned in the Inspector?", returning
site-rich results. 10 unit tests + 3 MCP integration checks.

## [1.5.0] -- pre-2.0 build-up

Scene-side parsing now tracks file-level line numbers. `attached_to`,
`subscribes_to`, and `overrides` edges carry sites with the matching
scene file path and line. UnityEvent listeners anchor on the
top-level MonoBehaviour field (not the nested `m_PersistentCalls`)
for click-through utility.

## [1.4.0] -- pre-2.0 build-up

Location-aware C# parser. New `CallSite` dataclass with line/col/snippet/
containing_method. Builder merges edges with deduplicated sites
(Roslyn-style). 8 unit tests + 5 integration tests.

## [1.3.0] -- pre-2.0 build-up

Evidence-schema groundwork (schema 1.2). `Site` / `SiteKind` /
`Confidence` types, `Edge.sites: list[Site]`, load/save roundtrip,
`Graph.sites_available()` flag.

## [1.2.0] -- Observatory

Live reactive force-directed visualization of the project graph
(`unitygraph viz`). HTML/CSS/JS bundled in `src/unitygraph/viz/assets/`.

## [1.1.x]

- `unitygraph update` for templates + graph refresh.
- Auto-rebuild hook so the graph stays fresh during a Claude Code session.

## [1.0.0]

Initial public bundle. `pyproject` extras, README, papers scaffold,
end-to-end verified on the bundled MiniUnityProject fixture.
