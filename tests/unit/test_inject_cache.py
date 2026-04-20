"""Tests for the in-process InjectCache that memoizes inject_context."""

from __future__ import annotations

from pathlib import Path

import pytest

from unitygraph.build.builder import build_project
from unitygraph.inject import cache as cache_mod
from unitygraph.inject.engine import inject_context

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject"


@pytest.fixture(scope="module")
def graph():
    return build_project(FIXTURE).graph


@pytest.fixture(autouse=True)
def _reset_default_cache():
    cache_mod.default_cache().clear()
    yield
    cache_mod.default_cache().clear()


def test_identical_calls_hit_cache(graph):
    default = cache_mod.default_cache()

    first = inject_context(graph, "fix slow on PlayerController", budget=1500)
    hits_after_first = default.hits
    misses_after_first = default.misses

    second = inject_context(graph, "fix slow on PlayerController", budget=1500)
    assert second.block == first.block
    assert default.misses == misses_after_first  # no additional miss
    assert default.hits == hits_after_first + 1  # one more hit


def test_different_task_is_separate_entry(graph):
    default = cache_mod.default_cache()

    inject_context(graph, "fix slow on PlayerController", budget=1500)
    inject_context(graph, "fix the Enemy detection", budget=1500)

    # Two distinct misses, no hits between them.
    assert default.misses == 2
    assert default.hits == 0


def test_different_budget_is_separate_entry(graph):
    default = cache_mod.default_cache()

    inject_context(graph, "fix slow on PlayerController", budget=1500)
    inject_context(graph, "fix slow on PlayerController", budget=500)
    assert default.misses == 2


def test_use_cache_false_bypasses_cache(graph):
    default = cache_mod.default_cache()

    inject_context(graph, "fix slow on PlayerController", budget=1500, use_cache=False)
    inject_context(graph, "fix slow on PlayerController", budget=1500, use_cache=False)

    assert default.hits == 0
    assert default.misses == 0


def test_make_key_hashes_task_text():
    k1 = cache_mod.make_key("a task", "g1", "auto", 2, 1500)
    k2 = cache_mod.make_key("a task  ", "g1", "auto", 2, 1500)  # whitespace normalized
    k3 = cache_mod.make_key("different task", "g1", "auto", 2, 1500)
    assert k1 == k2
    assert k1 != k3
