"""Tests for the Layer 3 observation loop."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from unitygraph.behavior import observer, schema
from unitygraph.build.builder import build_project
from unitygraph.cli import main
from unitygraph.inject.engine import inject_context

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject"


@pytest.fixture
def mini_graph():
    return build_project(FIXTURE).graph


@pytest.fixture
def isolated_project(tmp_path, mini_graph, monkeypatch):
    """Redirect the graph's project_root to a tmp dir so logs land in a
    predictable place we can clean up."""
    project = tmp_path / "proj"
    project.mkdir()
    mini_graph.project_root = str(project)
    monkeypatch.setenv("UNITYGRAPH_SESSION_ID", "s_test_fixed")
    return project, mini_graph


def test_observer_disabled_by_default(tmp_path, isolated_project):
    project, graph = isolated_project
    # No UNITYGRAPH_OBSERVE env var -> nothing written.
    assert not observer.observe_enabled()
    inject_context(graph, "fix slow on PlayerController")
    assert not (project / ".unitygraph" / "sessions").exists()


def test_observer_records_injection_when_enabled(isolated_project, monkeypatch):
    project, graph = isolated_project
    monkeypatch.setenv("UNITYGRAPH_OBSERVE", "1")

    inject_context(graph, "fix slow on PlayerController")

    sdir = schema.sessions_dir(project)
    assert sdir.exists()
    files = list(sdir.glob("*.jsonl"))
    assert files
    events = schema.iter_session_events(project, "s_test_fixed")
    assert any(e["event_type"] == "injection" for e in events)
    injection = next(e for e in events if e["event_type"] == "injection")
    assert injection["strategy"] == "entity_hop"
    assert "PlayerController" in injection["block"]


def test_observer_fire_and_forget_never_raises(tmp_path, monkeypatch):
    """Even if the filesystem is hostile, observer must not raise."""
    monkeypatch.setenv("UNITYGRAPH_OBSERVE", "1")

    # Passing a path that doesn't exist and can't be written -- the function
    # must swallow OSError and return silently.
    try:
        observer.record_feedback("/nonexistent-root-xyz", "s", "correct")
    except OSError:
        pytest.fail("observer.record_feedback should swallow OSError")
    except FileNotFoundError:
        pytest.fail("observer.record_feedback should swallow FileNotFoundError")
    except PermissionError:
        pytest.fail("observer.record_feedback should swallow PermissionError")


def test_feedback_cli_records_event(isolated_project, monkeypatch):
    project, graph = isolated_project
    monkeypatch.setenv("UNITYGRAPH_OBSERVE", "1")

    inject_context(graph, "fix slow on PlayerController")

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "feedback",
            "correct",
            "--project",
            str(project),
            "--note",
            "looks good",
        ],
    )
    assert result.exit_code == 0, result.output
    events = schema.iter_session_events(project, "s_test_fixed")
    assert any(e["event_type"] == "feedback" and e["verdict"] == "correct" for e in events)


def test_patterns_list_surface_events(isolated_project, monkeypatch):
    project, graph = isolated_project
    monkeypatch.setenv("UNITYGRAPH_OBSERVE", "1")

    inject_context(graph, "fix slow on PlayerController")
    observer.record_feedback(str(project), "s_test_fixed", "correct", note="manual")

    runner = CliRunner()
    result = runner.invoke(main, ["patterns", "list", "--project", str(project)])
    assert result.exit_code == 0
    assert "injection" in result.output
    assert "feedback" in result.output
