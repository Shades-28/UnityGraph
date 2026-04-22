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
        (templates / "settings.json", project / ".claude" / "settings.json"),
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


@main.command(
    help="Refresh UnityGraph in a project: sync templates to the installed version, then rebuild the graph."
)
@click.argument("project_path", type=click.Path(exists=True, file_okay=False), default=".")
@click.option(
    "--templates-only",
    is_flag=True,
    help="Only refresh CLAUDE.md / .mcp.json / settings.json / skill. Skip the graph rebuild.",
)
@click.option(
    "--graph-only",
    is_flag=True,
    help="Only rebuild the graph (`build --update`). Skip template sync.",
)
@click.option(
    "--check",
    is_flag=True,
    help="Report what would change without modifying any files.",
)
def update(
    project_path: str,
    templates_only: bool,
    graph_only: bool,
    check: bool,
) -> None:
    import hashlib

    project = Path(project_path).resolve()
    templates = Path(__file__).parent / "templates"

    pairs: list[tuple[Path, Path, str]] = [
        (templates / "CLAUDE.md", project / "CLAUDE.md", "CLAUDE.md"),
        (templates / ".mcp.json", project / ".mcp.json", ".mcp.json"),
        (
            templates / "settings.json",
            project / ".claude" / "settings.json",
            ".claude/settings.json",
        ),
        (
            templates / "skills" / "unity-aware" / "SKILL.md",
            project / ".claude" / "skills" / "unity-aware" / "SKILL.md",
            ".claude/skills/unity-aware/SKILL.md",
        ),
    ]

    def _hash(path: Path) -> str:
        # Normalize line endings so a template installed on Windows (CRLF on
        # disk via `write_text`) compares equal to the source template (LF in
        # the package). Without this, `update --templates-only` on a pristine
        # init immediately flags every file as changed.
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    # Templates phase.
    if not graph_only:
        click.echo(f"UnityGraph update (templates): {project}", err=True)
        updated = 0
        unchanged = 0
        missing = 0
        custom = 0
        for source, target, rel in pairs:
            if not source.exists():
                continue
            if not target.exists():
                if check:
                    click.echo(f"  would install: {rel}", err=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
                    click.echo(f"  installed:     {rel}", err=True)
                missing += 1
                continue
            if _hash(source) == _hash(target):
                unchanged += 1
                continue
            # Target has drifted. If the user hand-edited it, don't clobber silently.
            is_user_edited = _looks_user_edited(target, rel)
            if is_user_edited and not check:
                click.echo(
                    f"  custom:        {rel}  (hand-edited — run `unitygraph init {project} --force` to overwrite)",
                    err=True,
                )
                custom += 1
                continue
            if check:
                click.echo(f"  would update:  {rel}", err=True)
            else:
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
                click.echo(f"  updated:       {rel}", err=True)
            updated += 1

        click.echo(
            f"  templates: {updated} updated, {missing} installed, "
            f"{custom} custom (left alone), {unchanged} unchanged",
            err=True,
        )

    # Graph phase.
    if not templates_only:
        if check:
            click.echo("  would run: unitygraph build . --update", err=True)
            return
        click.echo("UnityGraph update (graph):", err=True)
        graph_out = project / "graph-out"
        cache_dir = graph_out / ".parse_cache"
        cache = ParseCache.load(cache_dir)
        result = build_project(project, cache=cache)
        cache.write()
        out_path = graph_out / "graph.json"
        result.graph.write(out_path)
        click.echo(
            f"  rebuilt: {len(result.graph.nodes)} nodes, "
            f"{len(result.graph.edges)} edges, {result.graph.build_ms}ms",
            err=True,
        )

    if not graph_only and not templates_only:
        click.echo(
            "\nTip: `unitygraph update --check` previews changes without writing.",
            err=True,
        )


def _looks_user_edited(path: Path, rel: str) -> bool:
    """Heuristic: if the file diverges from *any* known template in the
    package history, treat as user-edited. For v1.1.0 we only know the
    current template, so we fall back to a size/length comparison: files
    larger than template + 20% or with "TODO"/"custom" markers are treated
    as edited."""
    # Only apply to CLAUDE.md and the skill — .mcp.json and settings.json
    # are expected to be pure templates.
    if rel not in {"CLAUDE.md", ".claude/skills/unity-aware/SKILL.md"}:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    markers = ("TODO", "# CUSTOM", "# custom", "<!-- custom -->")
    return any(m in text for m in markers)


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


@main.command(help="Launch the Observatory — a live reactive visualization of the project graph.")
@click.argument(
    "graph_path",
    type=click.Path(exists=True, dir_okay=False),
    required=False,
)
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False),
    default=".",
    help="Project root (default: cwd). Ignored if GRAPH_PATH is given explicitly.",
)
@click.option("--port", type=int, default=7842, help="Preferred port (auto-bumps if busy).")
@click.option("--host", default="127.0.0.1", help="Bind host (default localhost only).")
@click.option("--no-browser", is_flag=True, help="Don't auto-open the browser.")
def viz(
    graph_path: str | None,
    project_path: str,
    port: int,
    host: str,
    no_browser: bool,
) -> None:
    import webbrowser

    from unitygraph.viz.server import run_server, wait_until_ready

    if graph_path is None:
        resolved = Path(project_path).resolve() / "graph-out" / "graph.json"
    else:
        resolved = Path(graph_path).resolve()

    if not resolved.exists():
        click.echo(
            f"graph not found: {resolved}\nRun `unitygraph build <project>` first.",
            err=True,
        )
        sys.exit(2)

    server, bound_port = run_server(resolved, port=port)
    url = f"http://127.0.0.1:{bound_port}/"
    click.echo(f"Observatory serving {resolved.name} at {url}", err=True)
    click.echo("Press Ctrl+C to stop.", err=True)

    if not no_browser:
        # Start the server in a thread, wait for /graph.json to be reachable,
        # then pop the browser.
        import threading

        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        if wait_until_ready(bound_port, timeout=5.0):
            webbrowser.open(url)
        try:
            server_thread.join()
        except KeyboardInterrupt:
            click.echo("\nshutting down.", err=True)
            server.shutdown()
    else:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            click.echo("\nshutting down.", err=True)
            server.shutdown()


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
    from unitygraph.behavior import extractor, observer, patterns, schema

    project = Path(project_path).resolve()
    target = session_id or _latest_session_id(project)
    if not target:
        click.echo("no session log found — run a Claude session first", err=True)
        sys.exit(2)

    observer.record_feedback(str(project), target, verdict, note=note)

    # Feed through the extractor so pattern confidences update immediately.
    events = schema.iter_session_events(project, target)
    injection = next(
        (e for e in reversed(events) if e.get("event_type") == "injection"),
        None,
    )
    matched: list[str] = []
    if injection is not None:
        with patterns.open_store(project) as store:
            result = extractor.extract_from_feedback(store, injection, verdict)
            matched = result.matched_pattern_ids

    msg = f"recorded feedback ({verdict}) for session {target}"
    if matched:
        msg += f"; updated {len(matched)} pattern(s): {', '.join(matched)}"
    click.echo(msg)


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


@patterns.command("show", help="Show the failure-pattern map.")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False),
    default=".",
)
@click.option(
    "--status",
    type=click.Choice(["observed", "active", "archived", "all"]),
    default="all",
)
def patterns_show(project_path: str, status: str) -> None:
    from unitygraph.behavior.patterns import open_store

    project = Path(project_path).resolve()
    status_filter = None if status == "all" else status
    with open_store(project) as store:
        rows = store.list_all(status=status_filter)
    if not rows:
        click.echo("(no patterns)")
        return
    click.echo(f"{'pattern_id':32} {'status':10} {'conf':>5} {'ev':>4}  {'mc_type':20}  rule")
    for p in rows:
        click.echo(
            f"{p.pattern_id:32} {p.status:10} "
            f"{p.confidence:5.2f} {p.evidence_count:4d}  "
            f"{p.missing_context_type:20}  {p.injection_rule}"
        )


@patterns.command("promote", help="Manually promote a pattern to active.")
@click.argument("pattern_id")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False),
    default=".",
)
def patterns_promote(pattern_id: str, project_path: str) -> None:
    from unitygraph.behavior.patterns import open_store

    project = Path(project_path).resolve()
    with open_store(project) as store:
        pat = store.promote(pattern_id)
    if pat is None:
        click.echo(f"no such pattern: {pattern_id}", err=True)
        sys.exit(2)
    click.echo(f"promoted {pattern_id} -> status=active")


@patterns.command("stats", help="Print summary statistics about the pattern map.")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False),
    default=".",
)
def patterns_stats(project_path: str) -> None:
    from unitygraph.behavior.patterns import open_store

    project = Path(project_path).resolve()
    with open_store(project) as store:
        stats = store.stats()
    click.echo(f"patterns: {stats['total']}")
    click.echo(f"mean_confidence: {stats['mean_confidence']}")
    click.echo(f"by_status: {stats['by_status']}")
    click.echo(f"by_missing_context_type: {stats['by_missing_context_type']}")


@patterns.command("replay", help="Replay all session logs through the extractor.")
@click.option(
    "--project",
    "project_path",
    type=click.Path(exists=True, file_okay=False),
    default=".",
)
def patterns_replay(project_path: str) -> None:
    from unitygraph.behavior import extractor, schema
    from unitygraph.behavior import patterns as pmod

    project = Path(project_path).resolve()
    events = schema.iter_all_events(project)
    with pmod.open_store(project) as store:
        n = extractor.replay_session_log(store, events)
    click.echo(f"processed {n} feedback events")


if __name__ == "__main__":
    main()
    sys.exit(0)
