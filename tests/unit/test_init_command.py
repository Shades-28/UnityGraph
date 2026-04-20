"""Tests for `unitygraph init` scaffolding a Unity project."""

from __future__ import annotations

from click.testing import CliRunner

from unitygraph.cli import main


def test_init_creates_claude_md_mcp_json_and_skill(tmp_path):
    project = tmp_path / "unity-proj"
    project.mkdir()

    runner = CliRunner()
    result = runner.invoke(main, ["init", str(project)])
    assert result.exit_code == 0, result.output

    assert (project / "CLAUDE.md").exists()
    assert (project / ".mcp.json").exists()
    assert (project / ".claude" / "skills" / "unity-aware" / "SKILL.md").exists()

    # The skill front-matter should have a name and description.
    skill_text = (project / ".claude" / "skills" / "unity-aware" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "name: unity-aware" in skill_text
    assert "description:" in skill_text


def test_init_skips_existing_without_force(tmp_path):
    project = tmp_path / "unity-proj"
    project.mkdir()
    existing = project / "CLAUDE.md"
    existing.write_text("my custom CLAUDE.md", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["init", str(project)])
    assert result.exit_code == 0
    assert existing.read_text(encoding="utf-8") == "my custom CLAUDE.md"


def test_init_force_overwrites(tmp_path):
    project = tmp_path / "unity-proj"
    project.mkdir()
    existing = project / "CLAUDE.md"
    existing.write_text("old", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["init", str(project), "--force"])
    assert result.exit_code == 0
    assert "UnityGraph" in existing.read_text(encoding="utf-8")


def test_init_no_skill_skips_skill_directory(tmp_path):
    project = tmp_path / "unity-proj"
    project.mkdir()

    runner = CliRunner()
    result = runner.invoke(main, ["init", str(project), "--no-skill"])
    assert result.exit_code == 0

    assert (project / "CLAUDE.md").exists()
    assert (project / ".mcp.json").exists()
    assert not (project / ".claude").exists()
