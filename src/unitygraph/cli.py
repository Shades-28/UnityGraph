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


@main.command(
    help="Initialize UnityGraph in a Unity project — writes CLAUDE.md, .mcp.json, and the Claude skill."
)
@click.argument("project_path", type=click.Path(exists=True, file_okay=False), default=".")
@click.option("--force", is_flag=True, help="Overwrite existing files.")
@click.option(
    "--no-skill",
    is_flag=True,
    help="Skip writing .claude/skills/unity-aware (useful for minimal installs).",
)
def init(project_path: str, force: bool, no_skill: bool) -> None:
    project = Path(project_path).resolve()
    templates = Path(__file__).parent / "templates"

    targets: list[tuple[Path, Path]] = [
        (templates / "CLAUDE.md", project / "CLAUDE.md"),
        (templates / ".mcp.json", project / ".mcp.json"),
    ]
    if not no_skill:
        targets.append(
            (
                templates / "skills" / "unity-aware" / "SKILL.md",
                project / ".claude" / "skills" / "unity-aware" / "SKILL.md",
            )
        )

    for source, target in targets:
        if target.exists() and not force:
            click.echo(
                f"skip (exists): {target.relative_to(project)}  (use --force to overwrite)",
                err=True,
            )
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        click.echo(f"wrote {target.relative_to(project)}")

    if not (project / "graph-out" / "graph.json").exists():
        click.echo(
            "\nnext: run `unitygraph build .` to produce graph-out/graph.json. "
            "Claude Code will pick up the MCP server automatically on the next "
            "session in this folder.",
            err=True,
        )


@main.command(help="Generate a UNITYGRAPH CONTEXT block for a task.")
@click.argument("task_text")
@click.option(
    "--graph",
    "graph_path",
    type=click.Path(exists=True, dir_okay=False),
    required=True,
    help="Path to graph.json.",
)
@click.option(
    "--strategy",
    type=click.Choice(["entity_hop", "task_type", "full_neighborhood"]),
    default=None,
    help="Retrieval strategy. Defaults to entity_hop when the task names entities.",
)
@click.option("--hops", type=int, default=2, help="BFS depth for entity_hop/task_type.")
@click.option("--budget", type=int, default=1500, help="Max tokens in the output block.")
def inject(
    task_text: str,
    graph_path: str,
    strategy: str | None,
    hops: int,
    budget: int,
) -> None:
    from unitygraph.build.graph import Graph
    from unitygraph.inject.engine import inject_context

    graph = Graph.load(Path(graph_path))
    result = inject_context(
        graph,
        task_text,
        strategy=strategy,  # type: ignore[arg-type]
        n_hops=hops,
        budget=budget,
    )
    click.echo(result.block)
    click.echo(
        f"\n[inject] strategy={result.strategy} confidence={result.confidence} "
        f"tokens={result.token_count}/{budget} nodes={result.node_count} "
        f"edges={result.edge_count} seeds={len(result.seed_node_ids)}",
        err=True,
    )


@main.command(help="Record feedback on a recent Claude session's output.")
@click.argument("verdict", type=click.Choice(["correct", "incorrect"]))
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False),
    default=".",
    help="Project root (defaults to cwd).",
)
@click.option(
    "--session",
    "session_id",
    default=None,
    help="Session id to attach the feedback to. Defaults to the most recent session in the log.",
)
@click.option("--note", default="", help="Free-form note attached to the feedback event.")
def feedback(verdict: str, project_path: str, session_id: str | None, note: str) -> None:
    from unitygraph.behavior import observer

    project = Path(project_path).resolve()
    target = session_id or _latest_session_id(project)
    if not target:
        click.echo("no session log found — run a Claude session first", err=True)
        sys.exit(2)

    observer.record_feedback(str(project), target, verdict, note=note)
    click.echo(f"recorded feedback ({verdict}) for session {target}")


def _latest_session_id(project_root: Path) -> str | None:
    from unitygraph.behavior.schema import sessions_dir

    sdir = sessions_dir(project_root)
    if not sdir.exists():
        return None
    files = sorted(sdir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    return files[-1].stem


@main.group(help="Observation and pattern management.")
def patterns() -> None:
    pass


@patterns.command("list", help="List recent session events.")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False),
    default=".",
)
@click.option("--limit", type=int, default=20, help="Max events to show.")
def patterns_list(project_path: str, limit: int) -> None:
    from unitygraph.behavior import schema

    project = Path(project_path).resolve()
    events = schema.iter_all_events(project)
    if not events:
        click.echo("no events recorded yet")
        return
    for event in events[-limit:]:
        etype = event.get("event_type", "?")
        sid = event.get("session_id", "?")
        ts = event.get("timestamp", "?")
        if etype == "injection":
            detail = (
                f"strategy={event.get('strategy')} "
                f"confidence={event.get('confidence')} "
                f"tokens={event.get('token_count')}"
            )
        elif etype == "feedback":
            detail = f"verdict={event.get('verdict')} note={event.get('note', '')!r}"
        elif etype == "correction":
            detail = f"diff={event.get('diff_summary', '')[:60]!r}"
        else:
            detail = ""
        click.echo(f"[{ts}] {etype:12} {sid:16} {detail}")


if __name__ == "__main__":
    main()
    sys.exit(0)
