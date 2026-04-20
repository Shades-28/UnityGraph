"""Tests for Layer 3 adaptive injection — matcher + engine integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from unitygraph.behavior import matcher, patterns
from unitygraph.build.builder import build_project
from unitygraph.inject import cache as cache_mod
from unitygraph.inject.engine import inject_context

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject"


@pytest.fixture
def isolated_project(tmp_path, monkeypatch):
    """Redirect graph.project_root to a tmp path so the pattern store and
    observer logs don't bleed across tests."""
    project = tmp_path / "proj"
    project.mkdir()
    return project


@pytest.fixture
def graph(isolated_project):
    g = build_project(FIXTURE).graph
    g.project_root = str(isolated_project)
    return g


@pytest.fixture
def active_pattern(isolated_project):
    """Open the pattern store for the isolated project and promote one pattern."""
    with patterns.open_store(isolated_project) as store:
        store.promote("seed_inspector_override_blindness")
    return "seed_inspector_override_blindness"


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_mod.default_cache().clear()
    yield
    cache_mod.default_cache().clear()


def test_matcher_returns_empty_when_no_store(tmp_path):
    hint = matcher.match_from_project(tmp_path, "fix something")
    assert hint.matched_patterns == []


def test_matcher_fires_for_active_pattern(isolated_project, active_pattern):
    hint = matcher.match_from_project(
        isolated_project,
        "fix the Inspector tuning for _speed",
    )
    assert any(p.pattern_id == active_pattern for p in hint.matched_patterns)
    assert hint.is_adaptive
    assert "attached_to" in hint.emphasize_edges
    assert hint.notes


def test_matcher_skips_observed_by_default(isolated_project):
    # Force seed (open_store auto-seeds on empty db).
    with patterns.open_store(isolated_project) as _:
        pass
    hint = matcher.match_from_project(isolated_project, "fix the Inspector tuning")
    # Default pre-seeds are observed, not active.
    assert not hint.is_adaptive


def test_matcher_include_observed_widens(isolated_project):
    with patterns.open_store(isolated_project) as _:
        pass
    hint = matcher.match_from_project(
        isolated_project,
        "fix the Inspector tuning",
        include_observed=True,
    )
    assert hint.is_adaptive


def test_adaptive_injection_adds_note(graph, active_pattern):
    result = inject_context(
        graph,
        "fix the Inspector tuning for _speed on PlayerController",
        adaptive=True,
    )
    assert result.adaptive
    assert active_pattern in result.matched_pattern_ids
    assert "ADAPTIVE INJECTION NOTES" in result.block
    assert "(adaptive)" in result.strategy


def test_static_injection_ignores_patterns(graph, active_pattern):
    result = inject_context(
        graph,
        "fix the Inspector tuning for _speed on PlayerController",
        adaptive=False,
    )
    assert not result.adaptive
    assert result.matched_pattern_ids == []
    assert "ADAPTIVE INJECTION NOTES" not in result.block


def test_adaptive_and_static_are_cached_separately(graph, active_pattern):
    default = cache_mod.default_cache()

    r_adaptive = inject_context(graph, "fix the Inspector tuning", adaptive=True)
    r_static = inject_context(graph, "fix the Inspector tuning", adaptive=False)
    assert r_adaptive.block != r_static.block
    assert default.misses == 2  # two distinct cache keys


def test_adaptive_hint_adds_hops(graph, isolated_project):
    with patterns.open_store(isolated_project) as store:
        store.promote("seed_event_connection_gap")

    result_adaptive = inject_context(
        graph,
        "wire up the UI button onClick event to PlayerController",
        adaptive=True,
    )
    result_static = inject_context(
        graph,
        "wire up the UI button onClick event to PlayerController",
        adaptive=False,
    )
    # Adaptive should have at least as many nodes (extra_hops=+1 for
    # event_connection rule). Could be equal if the graph is small.
    assert result_adaptive.node_count >= result_static.node_count
    assert result_adaptive.adaptive is True
