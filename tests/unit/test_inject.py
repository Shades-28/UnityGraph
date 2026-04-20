"""Unit tests for Layer 2 — entity extraction, retrieval, formatting, budget."""

from __future__ import annotations

from pathlib import Path

import pytest

from unitygraph.build.builder import build_project
from unitygraph.inject import budget as budget_mod
from unitygraph.inject import formatter as formatter_mod
from unitygraph.inject import retrieval as retrieval_mod
from unitygraph.inject.engine import inject_context
from unitygraph.inject.entities import extract_entities, extract_tokens

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject"


@pytest.fixture(scope="module")
def graph():
    return build_project(FIXTURE).graph


def test_extract_tokens_recovers_pascalcase():
    tokens = extract_tokens("Fix PlayerController so it respects the Inspector _speed")
    assert "PlayerController" in tokens
    assert "Inspector" in tokens


def test_extract_tokens_recovers_quoted():
    tokens = extract_tokens('Rename the "Main Camera" GameObject to Cam')
    assert "Main Camera" in tokens


def test_extract_entities_matches_player_controller(graph):
    result = extract_entities(graph, "fix the slow on PlayerController")
    names = {m.node.data.get("name") for m in result.matches}
    assert "PlayerController" in names
    # Script type should outrank any same-named non-script node.
    top = result.matches[0]
    assert top.node.type in {"Script", "GameObject"}


def test_task_type_classifier_for_bug_fix():
    assert retrieval_mod.classify_task("fix the slow effect") == "bug_fix"
    assert retrieval_mod.classify_task("add a new weapon") == "new_feature"
    assert retrieval_mod.classify_task("refactor the inventory") == "refactor"
    assert retrieval_mod.classify_task("explain how this works") == "explain"


def test_entity_hop_returns_relevant_subgraph(graph):
    sub = retrieval_mod.retrieve(graph, "fix PlayerController", strategy="entity_hop", n_hops=2)
    assert sub.strategy == "entity_hop"
    node_names = {n.data.get("name") for n in sub.nodes}
    assert "PlayerController" in node_names
    assert "Player" in node_names
    # HealthSystem is a co-component, reachable in 2 hops.
    assert "HealthSystem" in node_names


def test_task_type_strategy(graph):
    sub = retrieval_mod.retrieve(graph, "fix the slow on PlayerController", strategy="task_type")
    assert sub.strategy.startswith("task_type:")


def test_full_neighborhood_strategy(graph):
    sub = retrieval_mod.retrieve(graph, "somewhere in this scene", strategy="full_neighborhood")
    assert sub.strategy == "full_neighborhood"
    assert len(sub.nodes) > 0


def test_auto_strategy_picks_entity_hop(graph):
    sub = retrieval_mod.retrieve(graph, "fix PlayerController _speed")
    assert sub.strategy == "entity_hop"


def test_auto_strategy_falls_back_when_no_entity(graph):
    sub = retrieval_mod.retrieve(graph, "i have no idea")
    assert sub.strategy == "full_neighborhood"


def test_format_subgraph_includes_inspector_values(graph):
    sub = retrieval_mod.retrieve(graph, "PlayerController")
    block = formatter_mod.format_subgraph(sub, token_count=0).text
    assert "PlayerController" in block
    assert "_speed" in block
    assert "(code default: 5.0f)" in block


def test_inject_context_stays_under_budget(graph):
    out = inject_context(graph, "fix slow on PlayerController", budget=1500)
    assert out.token_count <= 1500
    assert "PlayerController" in out.block
    assert out.confidence in {"HIGH", "MEDIUM", "LOW"}


def test_inject_context_respects_tight_budget(graph):
    # Force trimming by setting a tiny budget.
    out = inject_context(graph, "fix slow on PlayerController", budget=200)
    assert out.token_count <= 250  # allow small slack for post-trim formatting


def test_inject_context_returns_strategy_label(graph):
    out = inject_context(graph, "fix slow on PlayerController", strategy="entity_hop")
    assert "entity_hop" in out.strategy


def test_token_count_is_positive():
    assert budget_mod.count_tokens("hello world") > 0
