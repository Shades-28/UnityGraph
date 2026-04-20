"""UnityGraph CLI entry point.

Subcommands land here as layers come online. I0 ships only `--help` and
`--version` — build/serve are filled in during Iteration 1.
"""

from __future__ import annotations

import sys

import click

from unitygraph import __version__


@click.group(help="UnityGraph — autonomous Unity developer system for Claude Code.")
@click.version_option(__version__, prog_name="unitygraph")
def main() -> None:
    pass


@main.command(help="Build a Unity project graph. [stub — implemented in Iteration 1]")
@click.argument("project_path", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output directory (default: <project>/graph-out).",
)
def build(project_path: str, output: str | None) -> None:
    click.echo(f"[I0 stub] build {project_path} -> {output or 'graph-out/'}", err=True)
    sys.exit(2)


@main.command(help="Serve a graph.json over MCP. [stub — implemented in Iteration 1]")
@click.argument("graph_path", type=click.Path(exists=True, dir_okay=False))
def serve(graph_path: str) -> None:
    click.echo(f"[I0 stub] serve {graph_path}", err=True)
    sys.exit(2)


if __name__ == "__main__":
    main()
