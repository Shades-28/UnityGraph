"""Tests for `unitygraph update` — template sync + graph rebuild."""

from __future__ import annotations

import shutil
from pathlib import Path

from click.testing import CliRunner

from unitygraph.cli import main

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject"


def _init_project(tmp_path, runner):
    project = tmp_path / "proj"
    project.mkdir()
    # Copy the fixture Unity assets so `build --update` has something to parse.
    shutil.copytree(FIXTURE / "Assets", project / "Assets")
    shutil.copytree(FIXTURE / "ProjectSettings", project / "ProjectSettings")
    result = runner.invoke(main, ["init", str(project)])
    assert result.exit_code == 0, result.output
    return project


def test_update_no_op_when_templates_match(tmp_path):
    runner = CliRunner()
    project = _init_project(tmp_path, runner)

    result = runner.invoke(main, ["update", str(project), "--templates-only"])
    assert result.exit_code == 0
    # "0 updated, 0 installed, ... 4 unchanged"
    assert "0 updated" in result.output
    assert "4 unchanged" in result.output


def test_update_refreshes_stale_template(tmp_path):
    runner = CliRunner()
    project = _init_project(tmp_path, runner)

    # Corrupt one template with obviously-wrong content (no TODO marker, so
    # the heuristic treats it as a stale installed template, not a user edit).
    mcp = project / ".mcp.json"
    mcp.write_text('{"old": true}', encoding="utf-8")

    result = runner.invoke(main, ["update", str(project), "--templates-only"])
    assert result.exit_code == 0
    assert "updated:" in result.output
    # After update, the file should contain the real template.
    assert "unitygraph.serve" in mcp.read_text(encoding="utf-8")


def test_update_preserves_user_edited_claude_md(tmp_path):
    runner = CliRunner()
    project = _init_project(tmp_path, runner)

    claude = project / "CLAUDE.md"
    claude.write_text(
        "# My custom notes\n\nTODO: remember to check the scene before edits.\n",
        encoding="utf-8",
    )

    result = runner.invoke(main, ["update", str(project), "--templates-only"])
    assert result.exit_code == 0
    assert "custom:" in result.output
    # File left untouched.
    assert "My custom notes" in claude.read_text(encoding="utf-8")


def test_update_check_is_dry_run(tmp_path):
    runner = CliRunner()
    project = _init_project(tmp_path, runner)

    mcp = project / ".mcp.json"
    mcp.write_text('{"old": true}', encoding="utf-8")
    snapshot = mcp.read_text(encoding="utf-8")

    result = runner.invoke(main, ["update", str(project), "--templates-only", "--check"])
    assert result.exit_code == 0
    assert "would update:" in result.output
    # File unchanged.
    assert mcp.read_text(encoding="utf-8") == snapshot


def test_update_rebuilds_graph_when_no_flag(tmp_path):
    runner = CliRunner()
    project = _init_project(tmp_path, runner)

    # Ensure there's no stale graph.
    graph_out = project / "graph-out"
    if graph_out.exists():
        shutil.rmtree(graph_out)

    result = runner.invoke(main, ["update", str(project)])
    assert result.exit_code == 0
    assert "rebuilt:" in result.output
    assert (project / "graph-out" / "graph.json").exists()


def test_update_graph_only_skips_templates(tmp_path):
    runner = CliRunner()
    project = _init_project(tmp_path, runner)

    # Corrupt a template; --graph-only should ignore it.
    mcp = project / ".mcp.json"
    mcp.write_text('{"old": true}', encoding="utf-8")

    result = runner.invoke(main, ["update", str(project), "--graph-only"])
    assert result.exit_code == 0
    assert "templates:" not in result.output
    assert "rebuilt:" in result.output
    # Template still the corrupted version — --graph-only didn't touch it.
    assert mcp.read_text(encoding="utf-8") == '{"old": true}'
