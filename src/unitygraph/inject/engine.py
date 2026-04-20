"""Top-level orchestrator: task text + graph → context block under a budget.

Pipeline:

1. Check the in-process ``InjectCache`` (keyed by task hash + graph identity).
2. **Consult the Layer 3 pattern matcher** (when ``adaptive=True``): any
   active pattern whose trigger fires contributes an ``AdaptationHint`` —
   extra hops, emphasized edge types, and human-readable notes appended
   to the block.
3. Entity extraction + retrieval (``entities`` + ``retrieval``).
4. Format the subgraph into the UNITYGRAPH CONTEXT block (``formatter``).
5. Count tokens (``budget``).
6. If over budget, trim nodes and re-format (up to ``max_iterations`` times).
7. Cache the result.
8. Fire the observation log entry.

The cache is a single-process LRU (128 entries) shared across the CLI and
MCP server. Pass ``use_cache=False`` for A/B tests where you need a fresh
compute every call. Pass ``adaptive=False`` to bypass the pattern matcher
(same thing — for A/B against the static L2 baseline).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from unitygraph.build.graph import Graph

from . import budget as budget_mod
from . import cache as cache_mod
from . import formatter as formatter_mod
from . import retrieval as retrieval_mod


@dataclass
class InjectionResult:
    block: str
    strategy: str
    confidence: str
    token_count: int
    node_count: int
    edge_count: int
    seed_node_ids: list[str]
    adaptive: bool = False
    matched_pattern_ids: list[str] = field(default_factory=list)


def inject_context(
    graph: Graph,
    task_text: str,
    *,
    strategy: retrieval_mod.Strategy | None = None,
    n_hops: int = 2,
    budget: int = 1500,
    use_cache: bool = True,
    graph_path: Path | None = None,
    adaptive: bool = True,
) -> InjectionResult:
    # Ask Layer 3 what, if anything, should be different.
    hint = None
    pattern_ids: list[str] = []
    if adaptive:
        try:
            from unitygraph.behavior.matcher import match_from_project

            project = Path(graph.project_root)
            hint = match_from_project(project, task_text)
            pattern_ids = [p.pattern_id for p in hint.matched_patterns]
        except ImportError:
            hint = None

    cache_obj = cache_mod.default_cache() if use_cache else None
    key: cache_mod.CacheKey | None = None
    if cache_obj is not None:
        graph_id = cache_mod.graph_identity(graph_path, graph.project_root)
        # Pattern-ids are part of the cache key so an evolving pattern map
        # invalidates stale injections automatically.
        strategy_key = (strategy or "auto") + (
            "|" + ",".join(sorted(pattern_ids)) if pattern_ids else ""
        )
        key = cache_mod.make_key(
            task_text,
            graph_id,
            strategy_key,
            n_hops + (hint.extra_hops if hint is not None else 0),
            budget,
        )
        hit = cache_obj.get(key)
        if hit is not None:
            return hit

    effective_hops = n_hops + (hint.extra_hops if hint is not None else 0)
    sub = retrieval_mod.retrieve(
        graph,
        task_text,
        strategy=strategy,
        n_hops=effective_hops,
    )

    if hint is not None and hint.emphasize_edges:
        sub = _extend_along_edges(graph, sub, hint.emphasize_edges)

    def _finalize(current: retrieval_mod.Subgraph, token_count: int) -> InjectionResult:
        formatted = formatter_mod.format_subgraph(current, token_count=token_count)
        block_text = formatted.text
        if hint is not None and hint.notes:
            block_text = (
                block_text.rstrip()
                + "\n\nADAPTIVE INJECTION NOTES\n"
                + "------------------------\n"
                + "\n".join(f"- {note}" for note in hint.notes)
                + "\n"
            )
            token_count = budget_mod.count_tokens(block_text)

        result = InjectionResult(
            block=block_text,
            strategy=current.strategy + (" (adaptive)" if hint and hint.is_adaptive else ""),
            confidence=formatted.confidence,
            token_count=token_count,
            node_count=len(current.nodes),
            edge_count=len(current.edges),
            seed_node_ids=list(current.seed_node_ids),
            adaptive=bool(hint and hint.is_adaptive),
            matched_pattern_ids=list(pattern_ids),
        )
        if cache_obj is not None and key is not None:
            cache_obj.put(key, result)
        # Fire-and-forget observation.
        try:
            from unitygraph.behavior import observer

            observer.record_injection(graph.project_root, task_text, result)
        except ImportError:
            pass
        return result

    # Iteratively trim until we fit the budget. Lower bound = keep seeds only.
    current = sub
    for _ in range(6):
        raw = formatter_mod.format_subgraph(current, token_count=0)
        token_count = budget_mod.count_tokens(raw.text)
        if token_count <= budget or len(current.nodes) <= max(4, len(current.seed_node_ids)):
            return _finalize(current, token_count)
        # Halve the node budget each iteration.
        target = max(len(current.seed_node_ids), len(current.nodes) // 2)
        current = formatter_mod.trim_to_budget(current, target)

    # Final pass.
    final_text = formatter_mod.format_subgraph(current, token_count=0).text
    return _finalize(current, budget_mod.count_tokens(final_text))


def _extend_along_edges(
    graph: Graph,
    sub: retrieval_mod.Subgraph,
    emphasize: set[str],
) -> retrieval_mod.Subgraph:
    """Add one-hop-along-emphasized-edge-types expansion to an existing subgraph.

    Lets the pattern matcher nudge the retrieval without redoing the full BFS.
    """
    if not sub.nodes:
        return sub
    existing_ids: set[str] = {n.id for n in sub.nodes}
    nodes_by_id = graph.nodes_by_id()
    new_node_ids: set[str] = set()
    new_edges = list(sub.edges)

    for edge in graph.edges:
        if edge.type not in emphasize:
            continue
        touches = edge.from_id in existing_ids or edge.to_id in existing_ids
        if not touches:
            continue
        if edge.from_id not in existing_ids and edge.from_id in nodes_by_id:
            new_node_ids.add(edge.from_id)
        if edge.to_id not in existing_ids and edge.to_id in nodes_by_id:
            new_node_ids.add(edge.to_id)

    if not new_node_ids:
        return sub

    updated_ids = existing_ids | new_node_ids
    new_nodes = list(sub.nodes) + [nodes_by_id[n] for n in new_node_ids]
    # Re-filter edges to only those fully inside the updated node set.
    all_edges = [e for e in graph.edges if e.from_id in updated_ids and e.to_id in updated_ids]
    # Preserve any edges we already had (they're a subset of all_edges now).
    _ = new_edges
    return retrieval_mod.Subgraph(
        nodes=new_nodes,
        edges=all_edges,
        strategy=sub.strategy + "+adapted",
        seed_node_ids=list(sub.seed_node_ids),
        entity_result=sub.entity_result,
    )
