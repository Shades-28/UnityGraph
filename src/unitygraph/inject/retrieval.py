"""Three retrieval strategies for task-relevant subgraphs.

Per plan §Iteration 4 and spec §2.3:

* ``entity_hop``: BFS from named-entity matches out to ``n_hops`` (default 2).
  Best when the task names specific entities like *"PlayerController"*.
* ``task_type``: map task type to a set of graph edge types + node types to
  prefer during expansion. Useful for *"fix the collision bug"*-style tasks
  that don't name a concrete entity yet.
* ``full_neighborhood``: god-nodes (highest degree) + 1-hop neighborhood of
  mentioned entities. Fallback when the task is ambiguous.

All strategies return a ``Subgraph`` (selected nodes + edges that touch those
nodes). The formatter + budget step consume it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from unitygraph.build.graph import Edge, Graph, Node

from .entities import EntityExtractionResult, extract_entities

Strategy = Literal["entity_hop", "task_type", "full_neighborhood"]


@dataclass
class Subgraph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    strategy: str = ""
    seed_node_ids: list[str] = field(default_factory=list)
    entity_result: EntityExtractionResult | None = None

    def node_ids(self) -> set[str]:
        return {n.id for n in self.nodes}


# Task type → edge types to emphasize during expansion.
TASK_TYPE_EDGE_EMPHASIS: dict[str, set[str]] = {
    "bug_fix": {
        "attached_to",
        "co_exists_with",
        "depends_on",
        "subscribes_to",
    },
    "new_feature": {
        "attached_to",
        "co_exists_with",
        "inherits",
        "depends_on",
    },
    "refactor": {
        "inherits",
        "depends_on",
        "calls",
    },
    "explain": {
        "attached_to",
        "co_exists_with",
        "subscribes_to",
        "is_variant_of",
    },
    "test": {
        "attached_to",
        "depends_on",
        "inherits",
    },
}


_TASK_TYPE_KEYWORDS: list[tuple[str, re.Pattern[str]]] = [
    (
        "bug_fix",
        re.compile(r"\b(fix|bug|broken|wrong|incorrect|crash|nullref|nullpointer)\b", re.I),
    ),
    (
        "new_feature",
        re.compile(r"\b(add|implement|create|introduce|build|new|support)\b", re.I),
    ),
    ("refactor", re.compile(r"\b(refactor|rename|extract|clean ?up|restructure)\b", re.I)),
    ("explain", re.compile(r"\b(explain|how does|why does|what does|describe)\b", re.I)),
    ("test", re.compile(r"\b(test|unit test|coverage|assert)\b", re.I)),
]


def classify_task(task_text: str) -> str:
    """Cheap heuristic → one of the five task types, or ``explain`` as default."""
    for label, pattern in _TASK_TYPE_KEYWORDS:
        if pattern.search(task_text):
            return label
    return "explain"


def retrieve(
    graph: Graph,
    task_text: str,
    *,
    strategy: Strategy | None = None,
    n_hops: int = 2,
) -> Subgraph:
    """Run the requested retrieval strategy (or auto-pick one)."""
    entity_result = extract_entities(graph, task_text)

    if strategy is None:
        strategy = "entity_hop" if entity_result.matches else "full_neighborhood"

    if strategy == "entity_hop":
        return _entity_hop(graph, entity_result, n_hops=n_hops)
    if strategy == "task_type":
        return _task_type(graph, entity_result, task_text, n_hops=n_hops)
    if strategy == "full_neighborhood":
        return _full_neighborhood(graph, entity_result)

    raise ValueError(f"unknown strategy: {strategy}")


def _entity_hop(graph: Graph, entity_result: EntityExtractionResult, *, n_hops: int) -> Subgraph:
    seeds = _top_seeds(entity_result)
    if not seeds:
        return Subgraph(strategy="entity_hop", entity_result=entity_result)

    adjacency = _build_adjacency(graph)
    seen: set[str] = set(seeds)
    frontier = list(seeds)
    for _ in range(n_hops):
        next_frontier: list[str] = []
        for nid in frontier:
            for nbr in adjacency.get(nid, ()):
                if nbr not in seen:
                    seen.add(nbr)
                    next_frontier.append(nbr)
        frontier = next_frontier

    return _materialize(
        graph, seen, strategy="entity_hop", seeds=seeds, entity_result=entity_result
    )


def _task_type(
    graph: Graph,
    entity_result: EntityExtractionResult,
    task_text: str,
    *,
    n_hops: int,
) -> Subgraph:
    task_type = classify_task(task_text)
    emphasis = TASK_TYPE_EDGE_EMPHASIS.get(task_type, set())
    seeds = _top_seeds(entity_result)
    if not seeds:
        # No entities — degrade to full_neighborhood, keep strategy label.
        fallback = _full_neighborhood(graph, entity_result)
        fallback.strategy = f"task_type:{task_type}"
        return fallback

    adjacency = _build_typed_adjacency(graph)
    seen: set[str] = set(seeds)
    frontier = list(seeds)
    for _ in range(n_hops):
        next_frontier: list[str] = []
        for nid in frontier:
            for nbr, etype in adjacency.get(nid, ()):
                if nbr in seen:
                    continue
                if emphasis and etype not in emphasis:
                    continue
                seen.add(nbr)
                next_frontier.append(nbr)
        frontier = next_frontier

    sub = _materialize(
        graph, seen, strategy=f"task_type:{task_type}", seeds=seeds, entity_result=entity_result
    )
    return sub


def _full_neighborhood(graph: Graph, entity_result: EntityExtractionResult) -> Subgraph:
    # Pick top-degree nodes (god-nodes) + 1-hop around mentioned entities.
    adjacency = _build_adjacency(graph)
    degree = {nid: len(nbrs) for nid, nbrs in adjacency.items()}
    top_n = 10
    god_ids = [nid for nid, _ in sorted(degree.items(), key=lambda x: -x[1])[:top_n]]

    seeds = _top_seeds(entity_result) or god_ids
    seen: set[str] = set(god_ids) | set(seeds)
    for nid in list(seeds):
        for nbr in adjacency.get(nid, ()):
            seen.add(nbr)
    return _materialize(
        graph, seen, strategy="full_neighborhood", seeds=seeds, entity_result=entity_result
    )


def _top_seeds(entity_result: EntityExtractionResult, max_seeds: int = 8) -> list[str]:
    # Keep distinct node ids, highest-score first.
    ids: list[str] = []
    added: set[str] = set()
    for m in entity_result.matches:
        if m.node.id in added:
            continue
        ids.append(m.node.id)
        added.add(m.node.id)
        if len(ids) >= max_seeds:
            break
    return ids


def _build_adjacency(graph: Graph) -> dict[str, set[str]]:
    adj: dict[str, set[str]] = defaultdict(set)
    for e in graph.edges:
        adj[e.from_id].add(e.to_id)
        adj[e.to_id].add(e.from_id)
    return adj


def _build_typed_adjacency(graph: Graph) -> dict[str, list[tuple[str, str]]]:
    adj: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in graph.edges:
        adj[e.from_id].append((e.to_id, e.type))
        adj[e.to_id].append((e.from_id, e.type))
    return adj


def _materialize(
    graph: Graph,
    node_ids: set[str],
    *,
    strategy: str,
    seeds: list[str],
    entity_result: EntityExtractionResult,
) -> Subgraph:
    nodes_by_id = graph.nodes_by_id()
    nodes = [nodes_by_id[nid] for nid in node_ids if nid in nodes_by_id]
    edges = [e for e in graph.edges if e.from_id in node_ids and e.to_id in node_ids]
    return Subgraph(
        nodes=nodes,
        edges=edges,
        strategy=strategy,
        seed_node_ids=seeds,
        entity_result=entity_result,
    )
