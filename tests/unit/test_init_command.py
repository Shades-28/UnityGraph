"""Tests for `unitygraph init` scaffolding a Unity project."""

from __future__ import annotations

from click.testing import CliRunner

from unitygraph.cli import main


def test_init_creates_claude_md_mcp_json_settings_and_skill(tmp_path):
    project = tmp_path / "unity-proj"
    project.mkdir()

    runner = CliRunner()
    result = runner.invoke(main, ["init", str(project)])
    assert result.exit_code == 0, result.output

    assert (project / "CLAUDE.md").exists()
    assert (project / ".mcp.json").exists()
    assert (project / ".claude" / "settings.json").exists()
    assert (project / ".claude" / "skills" / "unity-aware" / "SKILL.md").exists()

    # The skill front-matter should have a name and description.
    skill_text = (project / ".claude" / "skills" / "unity-aware" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "name: unity-aware" in skill_text
    assert "description:" in skill_text


def test_init_settings_contains_auto_rebuild_hook(tmp_path):
    """Proves the Stop hook that runs `unitygraph build . --update` is wired."""
    import json

    project = tmp_path / "unity-proj"
    project.mkdir()

    runner = CliRunner()
    result = runner.invoke(main, ["init", str(project)])
    assert result.exit_code == 0

    settings = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "hooks" in settings
    assert "Stop" in settings["hooks"]
    stop_commands = [
        h.get("command", "") for group in settings["hooks"]["Stop"] for h in group.get("hooks", [])
    ]
    assert any("unitygraph build" in c and "--update" in c for c in stop_commands)


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
    # settings.json still written -- the auto-rebuild hook is orthogonal to the skill.
    assert (project / ".claude" / "settings.json").exists()
    assert not (project / ".claude" / "skills").exists()


def test_init_demo_scaffolds_unity_project(tmp_path):
    """v2.2: --demo creates a fresh Unity demo project at the path."""
    project = tmp_path / "demo-project"
    # Path must NOT exist beforehand.
    runner = CliRunner()
    result = runner.invoke(main, ["init", str(project), "--demo"])
    assert result.exit_code == 0, result.output

    # Demo Unity project files
    assert (project / "Assets").is_dir()
    assert (project / "ProjectSettings").is_dir()
    # And UnityGraph templates installed inside it
    assert (project / "CLAUDE.md").exists()
    assert (project / ".mcp.json").exists()
    assert (project / ".claude" / "settings.json").exists()


def test_init_demo_refuses_to_overwrite_existing_directory(tmp_path):
    """--demo must NOT clobber an existing non-empty directory."""
    project = tmp_path / "existing"
    project.mkdir()
    (project / "important.txt").write_text("don't lose me", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["init", str(project), "--demo"])
    assert result.exit_code != 0
    assert (project / "important.txt").exists(), "must not have wiped existing contents"


def test_init_demo_accepts_empty_existing_directory(tmp_path):
    """v2.1.3 regression: `unitygraph init --demo .` against an empty
    existing directory must succeed. Was crashing in shutil.copytree
    because dirs_exist_ok=False refused even an empty target.
    """
    project = tmp_path / "empty"
    project.mkdir()  # exists but empty -- like `mkdir foo; cd foo; unitygraph init --demo .`

    runner = CliRunner()
    result = runner.invoke(main, ["init", str(project), "--demo"])
    assert result.exit_code == 0, result.output
    assert (project / "Assets").is_dir()
    assert (project / "CLAUDE.md").exists()
