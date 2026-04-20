"""UnityGraph CLI entry point.

Subcommands:

* ``unitygraph build <project_path> [--output DIR]``   — emit ``graph.json``
* ``unitygraph serve <graph.json>``                     — run the MCP server

Further subcommands (``inject``, ``feedback``, ``patterns``) land in later
iterations per ``UnityGraph_Development_Plan.md``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from unitygraph import __version__
from unitygraph.build.builder import build_project
from unitygraph.build.cache import ParseCache


@click.group(help="UnityGraph — autonomous Unity developer system for Claude Code.")
@click.version_option(__version__, prog_name="unitygraph")
def main() -> None:
    pass


@main.command(help="Build a Unity project graph from PROJECT_PATH.")
@click.argument("project_path", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output directory (default: <project>/graph-out).",
)
@click.option(
    "--update",
    is_flag=True,
    help="Incremental build: reuse cached parser output for files unchanged since the last build.",
)
@click.option("-v", "--verbose", is_flag=True, help="Print per-file warnings as they occur.")
def build(project_path: str, output: str | None, update: bool, verbose: bool) -> None:
    project = Path(project_path).resolve()
    out_dir = Path(output).resolve() if output else project / "graph-out"
    cache_dir = out_dir / ".parse_cache"

    cache: ParseCache | None = None
    if update:
        cache = ParseCache.load(cache_dir)
        click.echo(
            f"Building graph (incremental, cached={len(cache.entries)} entries) "
            f"for {project} -> {out_dir}",
            err=True,
        )
    else:
        click.echo(f"Building graph for {project} -> {out_dir}", err=True)
    result = build_project(project, cache=cache)

    if cache is not None:
        cache.write()

    out_path = out_dir / "graph.json"
    result.graph.write(out_path)

    report = result.report
    click.echo(
        f"  scripts: {report.n_cs}  scenes: {report.n_scenes}  prefabs: {report.n_prefabs}"
        f"  nodes: {len(result.graph.nodes)}  edges: {len(result.graph.edges)}"
        f"  time: {result.graph.build_ms}ms",
        err=True,
    )
    if report.warnings:
        tallies = report.tallies()
        summary = "  ".join(f"{cat}={n}" for cat, n in sorted(tallies.items()))
        click.echo(f"  warnings: {len(report.warnings)}  ({summary})", err=True)
        if verbose:
            for w in report.warnings:
                click.echo(f"    ! [{w.category}] {w.path}: {w.message}", err=True)
    click.echo(f"Wrote {out_path}")


@main.command(help="Serve a graph.json over MCP (stdio).")
@click.argument("graph_path", type=click.Path(exists=True, dir_okay=False))
def serve(graph_path: str) -> None:
    # Import lazily — mcp pulls in anyio and starts an event loop.
    from unitygraph.mcp.server import run_stdio_server

    run_stdio_server(Path(graph_path).resolve())


if __name__ == "__main__":
    main()
    sys.exit(0)
