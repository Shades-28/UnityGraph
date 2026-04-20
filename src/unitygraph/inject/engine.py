"""Top-level orchestrator: task text + graph → context block under a budget.

Pipeline:

1. Entity extraction + retrieval (``entities`` + ``retrieval``).
2. Format the subgraph into the UNITYGRAPH CONTEXT block (``formatter``).
3. Count tokens (``budget``).
4. If over budget, trim nodes and re-format (up to ``max_iterations`` times).
"""

from __future__ import annotations

from dataclasses import dataclass

from unitygraph.build.graph import Graph

from . import budget as budget_mod
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
) -> InjectionResult:
    sub = retrieval_mod.retrieve(graph, task_text, strategy=strategy, n_hops=n_hops)

    # Iteratively trim until we fit the budget. Lower bound = keep seeds only.
    current = sub
    for _ in range(6):
        raw = formatter_mod.format_subgraph(current, token_count=0)
        token_count = budget_mod.count_tokens(raw.text)
        if token_count <= budget or len(current.nodes) <= max(4, len(current.seed_node_ids)):
            formatted = formatter_mod.format_subgraph(current, token_count=token_count)
            return InjectionResult(
                block=formatted.text,
                strategy=current.strategy,
                confidence=formatted.confidence,
                token_count=token_count,
                node_count=len(current.nodes),
                edge_count=len(current.edges),
                seed_node_ids=list(current.seed_node_ids),
            )
        # Halve the node budget each iteration.
        target = max(len(current.seed_node_ids), len(current.nodes) // 2)
        current = formatter_mod.trim_to_budget(current, target)

    # Final pass.
    formatted = formatter_mod.format_subgraph(current, token_count=budget_mod.count_tokens("final"))
    token_count = budget_mod.count_tokens(formatted.text)
    return InjectionResult(
        block=formatted.text,
        strategy=current.strategy,
        confidence=formatted.confidence,
        token_count=token_count,
        node_count=len(current.nodes),
        edge_count=len(current.edges),
        seed_node_ids=list(current.seed_node_ids),
    )
