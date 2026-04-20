"""Task text → candidate graph entities.

Given a developer task string like *"fix the slow effect on PlayerController
so it matches the Player Inspector speed"*, extract the tokens most likely to
name graph nodes (``PlayerController``, ``Player``, ``Inspector``, ``speed``)
and rank them against the graph's Script / GameObject / Prefab / Scene names.

No LLM — this is cheap deterministic regex matching. Layer 3 may later feed
back signals to nudge the ranking, but the skeleton stays rule-based.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from unitygraph.build.graph import Graph, Node

# PascalCase or snake_case identifiers of length >= 3, plus anything inside
# straight quotes. Very forgiving — we over-extract then filter against the
# graph on the retrieval side.
_TOKEN_RE = re.compile(r"[A-Z][A-Za-z0-9]{2,}|[a-z_][a-z0-9_]{2,}|\"([^\"]+)\"|'([^']+)'")


@dataclass
class EntityMatch:
    token: str
    node: Node
    score: float


@dataclass
class EntityExtractionResult:
    tokens: list[str]
    matches: list[EntityMatch]


def extract_tokens(text: str) -> list[str]:
    """Return the candidate identifier tokens in ``text``.

    Tokens come out as seen (preserving case) — retrieval lowercases when
    needed. Duplicates are removed while preserving order.
    """
    seen: dict[str, None] = {}
    for m in _TOKEN_RE.finditer(text):
        token = m.group(1) or m.group(2) or m.group(0)
        if not token or len(token) < 3:
            continue
        seen.setdefault(token, None)
    return list(seen)


def extract_entities(graph: Graph, task_text: str) -> EntityExtractionResult:
    """Return graph nodes that match tokens in ``task_text``.

    Matching is case-insensitive against node ``data["name"]``. Each token can
    match multiple nodes (e.g. *"Player"* → one GameObject per scene). Ranking
    heuristic: exact-case matches > case-insensitive; Script > GameObject >
    Prefab > Scene > Component (longer names preferred).
    """
    tokens = extract_tokens(task_text)
    if not tokens:
        return EntityExtractionResult(tokens=[], matches=[])

    by_name: dict[str, list[Node]] = {}
    for n in graph.nodes:
        name = str(n.data.get("name", ""))
        if not name:
            continue
        by_name.setdefault(name.lower(), []).append(n)

    priority = {
        "Script": 5,
        "GameObject": 4,
        "Prefab": 3,
        "Scene": 2,
        "AnimatorController": 2,
        "ShaderGraph": 2,
        "Component": 1,
        "AnimState": 1,
    }

    matches: list[EntityMatch] = []
    for token in tokens:
        candidates = by_name.get(token.lower(), [])
        for node in candidates:
            exact = str(node.data.get("name", "")) == token
            score = priority.get(node.type, 0) + (0.5 if exact else 0.0)
            matches.append(EntityMatch(token=token, node=node, score=score))

    matches.sort(key=lambda m: m.score, reverse=True)
    return EntityExtractionResult(tokens=tokens, matches=matches)
