"""Top-level orchestrator: task text + graph → context block under a budget.

Pipeline:

1. Check the in-process ``InjectCache`` (keyed by task hash + graph identity).
2. Entity extraction + retrieval (``entities`` + ``retrieval``).
3. Format the subgraph into the UNITYGRAPH CONTEXT block (``formatter``).
4. Count tokens (``budget``).
5. If over budget, trim nodes and re-format (up to ``max_iterations`` times).
6. Cache the result.

The cache is a single-process LRU (128 entries) shared across the CLI and
MCP server. Pass ``use_cache=False`` for A/B tests where you need a fresh
compute every call.
"""

from __future__ import annotations

from dataclasses import dataclass
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


def inject_context(
    graph: Graph,
    task_text: str,
    *,
    strategy: retrieval_mod.Strategy | None = None,
    n_hops: int = 2,
    budget: int = 1500,
    use_cache: bool = True,
    graph_path: Path | None = None,
) -> InjectionResult:
    cache_obj = cache_mod.default_cache() if use_cache else None
    key: cache_mod.CacheKey | None = None
    if cache_obj is not None:
        graph_id = cache_mod.graph_identity(graph_path, graph.project_root)
        key = cache_mod.make_key(
            task_text,
            graph_id,
            strategy or "auto",
            n_hops,
            budget,
        )
        hit = cache_obj.get(key)
        if hit is not None:
            return hit

    sub = retrieval_mod.retrieve(graph, task_text, strategy=strategy, n_hops=n_hops)

    def _finalize(current: retrieval_mod.Subgraph, token_count: int) -> InjectionResult:
        formatted = formatter_mod.format_subgraph(current, token_count=token_count)
        result = InjectionResult(
            block=formatted.text,
            strategy=current.strategy,
            confidence=formatted.confidence,
            token_count=token_count,
            node_count=len(current.nodes),
            edge_count=len(current.edges),
            seed_node_ids=list(current.seed_node_ids),
        )
        if cache_obj is not None and key is not None:
            cache_obj.put(key, result)
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
