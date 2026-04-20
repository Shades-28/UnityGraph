"""Unit tests for the UnityBench harness — task loading, conditions, scoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.unitybench.harness import (
    Task,
    build_condition_baseline,
    build_condition_manual_visual,
    build_condition_unitygraph,
    discover_tasks,
    score_response,
)
from unitygraph.build.builder import build_project

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject"


@pytest.fixture(scope="module", autouse=True)
def _ensure_graph_built():
    """Build graph.json so unitygraph condition + graph-path lookups work."""
    graph_path = FIXTURE / "graph-out" / "graph.json"
    if not graph_path.exists():
        result = build_project(FIXTURE)
        result.graph.write(graph_path)


def test_discover_tasks_finds_mvp_set():
    tasks = discover_tasks()
    assert len(tasks) >= 19
    tiers = {t.tier for t in tasks}
    assert tiers == {1, 2, 3}

    tier_counts = {
        1: sum(1 for t in tasks if t.tier == 1),
        2: sum(1 for t in tasks if t.tier == 2),
        3: sum(1 for t in tasks if t.tier == 3),
    }
    assert tier_counts[1] >= 6
    assert tier_counts[2] >= 10
    assert tier_counts[3] >= 3


def test_task_load_headline():
    task_dir = (
        Path(__file__).parents[2]
        / "evals"
        / "unitybench"
        / "tasks"
        / "t2_001_slow_proportional_to_speed"
    )
    task = Task.load(task_dir)
    assert task.task_id == "t2_001_slow_proportional_to_speed"
    assert task.tier == 2
    assert task.requires_scene_context is True
    assert "PlayerController" in task.relevant_entities


def test_condition_baseline_contains_only_source():
    task = _headline_task()
    prompt = build_condition_baseline(task)
    assert "PlayerController" in prompt
    assert "Inspector" not in prompt or "[SerializeField]" in prompt
    # No UNITYGRAPH CONTEXT block.
    assert "=== UNITYGRAPH CONTEXT ===" not in prompt


def test_condition_manual_visual_adds_description():
    task = _headline_task()
    baseline = build_condition_baseline(task)
    manual = build_condition_manual_visual(task)
    assert len(manual) > len(baseline)
    assert "scene context" in manual.lower() or "inspector" in manual.lower()


def test_condition_unitygraph_adds_context_block():
    task = _headline_task()
    prompt = build_condition_unitygraph(task)
    assert "=== UNITYGRAPH CONTEXT ===" in prompt


def test_score_response_recognizes_correct_fix():
    task = _headline_task()
    # Simulated correct fix:
    correct = (
        "Here's the fix:\n```diff\n"
        "-            _speedMultiplier = Mathf.Max(0.1f, 1.0f - (amount / 5.0f));\n"
        "+            _speedMultiplier = Mathf.Max(0.1f, 1.0f - (amount / _speed));\n"
        "```\n"
    )
    score = score_response(task, correct, injected_context_tokens=100)
    assert score.runtime_correctness == 1.0


def test_score_response_rejects_baseline_wrong_answer():
    task = _headline_task()
    # Claude kept the wrong literal 5.0f
    wrong = (
        "The math is already correct:\n"
        "```diff\n"
        " _speedMultiplier = Mathf.Max(0.1f, 1.0f - (amount / 5.0f));\n"
        "```\n"
    )
    score = score_response(task, wrong, injected_context_tokens=0)
    assert score.runtime_correctness == 0.0


def _headline_task() -> Task:
    return Task.load(
        Path(__file__).parents[2]
        / "evals"
        / "unitybench"
        / "tasks"
        / "t2_001_slow_proportional_to_speed"
    )
