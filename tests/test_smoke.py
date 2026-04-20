"""I0 smoke tests — verify the package is importable and CLI wiring is sane."""

from __future__ import annotations

from click.testing import CliRunner

import unitygraph
from unitygraph.cli import main


def test_package_importable() -> None:
    assert unitygraph.__version__


def test_cli_help_works() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "UnityGraph" in result.output


def test_cli_version_flag() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert unitygraph.__version__ in result.output


def test_build_subcommand_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["build", "--help"])
    assert result.exit_code == 0
    assert "PROJECT_PATH" in result.output.upper() or "project_path" in result.output


def test_serve_subcommand_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["serve", "--help"])
    assert result.exit_code == 0
