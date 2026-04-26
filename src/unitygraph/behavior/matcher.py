"""Pattern matcher -- bridges the pattern map to Layer 2 retrieval.

Given a task string and the graph, return the set of **active** patterns
whose triggers fire, along with a merged ``AdaptationHint`` that tells
Layer 2 what to do differently vs its static strategy:

- ``extra_hops``: add this many BFS hops to entity_hop / task_type
  retrieval (cap at 4).
- ``always_emphasize_edges``: extra edge types the retrieval should
  prefer when expanding (union with any task_type emphasis).
- ``extra_tools``: names of MCP tools the formatter should invoke to
  enrich the block (e.g. ``get_event_connections`` for the
  Event-Connection-Gap pattern).
- ``notes``: human-readable strings appended to the formatted block so
  the developer (and Claude) can see which patterns influenced the
  retrieval.

All heavy lifting lives here; the engine consumes the hint and applies
it uniformly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .patterns import Pattern, PatternStore

# Map spec missing_context_type values to concrete retrieval directives.
# Each rule is (extra_hops, emphasize_edges, extra_tools, note_template).
_RULES: dict[str, dict[str, Any]] = {
    "co_component": {
        "extra_hops": 1,
        "emphasize_edges": {"co_exists_with", "attached_to"},
        "extra_tools": ("get_components",),
        "note": "pattern {id}: expanding +1 hop along co_exists_with",
    },
    "inspector_value": {
        "extra_hops": 0,
        "emphasize_edges": {"attached_to"},
        "extra_tools": ("get_inspector_values",),
        "note": "pattern {id}: enriching with Inspector-value overrides",
    },
    "lifecycle_order": {
        "extra_hops": 0,
        "emphasize_edges": {"co_exists_with"},
        "extra_tools": (),
        "note": "pattern {id}: including script execution order on all scripts in scope",
    },
    "event_connection": {
        "extra_hops": 1,
        "emphasize_edges": {"subscribes_to", "attached_to"},
        "extra_tools": ("get_event_connections",),
        "note": "pattern {id}: surfacing full UnityEvent wiring",
    },
    "prefab_override": {
        "extra_hops": 0,
        "emphasize_edges": {"is_variant_of", "overrides"},
        "extra_tools": ("get_prefab_chain",),
        "note": "pattern {id}: walking prefab chain with overrides",
    },
    "coroutine_destroy": {
        "extra_hops": 1,
        "emphasize_edges": {"attached_to", "co_exists_with"},
        "extra_tools": (),
        "note": "pattern {id}: injecting active-state + destruction context for coroutines",
    },
    "parent_component": {
        "extra_hops": 1,
        "emphasize_edges": {"attached_to"},
        "extra_tools": (),
        "note": "pattern {id}: adding parent-component hop",
    },
}


@dataclass
class AdaptationHint:
    matched_patterns: list[Pattern] = field(default_factory=list)
    extra_hops: int = 0
    emphasize_edges: set[str] = field(default_factory=set)
    extra_tools: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)

    @property
    def is_adaptive(self) -> bool:
        return bool(self.matched_patterns)


def match(
    store: PatternStore,
    task_text: str,
    *,
    include_observed: bool = False,
) -> AdaptationHint:
    """Return the merged hint for all patterns that fire on ``task_text``.

    ``include_observed=True`` widens to all non-archived patterns (used for
    A/B ablations); default ``False`` means only ``active`` patterns
    influence retrieval so low-evidence patterns don't perturb production.
    """
    hint = AdaptationHint()
    statuses = {"active"} if not include_observed else {"active", "observed"}

    for pat in store.list_all():
        if pat.status not in statuses:
            continue
        try:
            if not re.search(pat.trigger, task_text, re.IGNORECASE):
                continue
        except re.error:
            continue

        rule = _RULES.get(pat.missing_context_type)
        if rule is None:
            continue

        hint.matched_patterns.append(pat)
        hint.extra_hops = min(4, hint.extra_hops + int(rule["extra_hops"]))
        hint.emphasize_edges |= set(rule["emphasize_edges"])
        hint.extra_tools |= set(rule["extra_tools"])
        hint.notes.append(rule["note"].format(id=pat.pattern_id))

    return hint


def match_from_project(
    project_root: Path,
    task_text: str,
    *,
    include_observed: bool = False,
) -> AdaptationHint:
    """Convenience wrapper: open the default store and match."""
    from .patterns import default_store_path

    db = default_store_path(project_root)
    if not db.exists():
        return AdaptationHint()
    with PatternStore(db) as store:
        return match(store, task_text, include_observed=include_observed)


__all__ = ["AdaptationHint", "match", "match_from_project"]
