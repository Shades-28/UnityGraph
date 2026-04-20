"""Core UnityBench harness: load task, run condition, score output.

Separated from runner.py so the scoring / IO / condition logic is unit-testable
without live Claude API calls.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from unitygraph.build.graph import Graph

REPO_ROOT = Path(__file__).parents[2]


@dataclass
class Task:
    """One UnityBench task."""

    task_id: str
    task_dir: Path
    tier: int
    project: str
    graph_path: Path
    source_files: list[Path]
    relevant_entities: list[str]
    task_type: str
    requires_scene_context: bool
    task_text: str
    ground_truth: str
    metadata: dict[str, Any]

    @classmethod
    def load(cls, task_dir: Path) -> Task:
        meta = yaml.safe_load((task_dir / "metadata.yml").read_text(encoding="utf-8"))
        task_text = (task_dir / "task.md").read_text(encoding="utf-8")
        ground_truth = (task_dir / "ground_truth.patch").read_text(encoding="utf-8")
        return cls(
            task_id=task_dir.name,
            task_dir=task_dir,
            tier=int(meta.get("tier", 0)),
            project=str(meta.get("project", "")),
            graph_path=REPO_ROOT / str(meta.get("graph_path", "")),
            source_files=[REPO_ROOT / p for p in meta.get("source_files", [])],
            relevant_entities=list(meta.get("relevant_entities", [])),
            task_type=str(meta.get("task_type", "")),
            requires_scene_context=bool(meta.get("requires_scene_context", False)),
            task_text=task_text,
            ground_truth=ground_truth,
            metadata=meta,
        )


def discover_tasks(tasks_dir: Path | None = None) -> list[Task]:
    """Load every task in ``evals/unitybench/tasks/``."""
    root = tasks_dir or (Path(__file__).parent / "tasks")
    tasks: list[Task] = []
    for task_dir in sorted(root.iterdir()):
        if not task_dir.is_dir():
            continue
        if not (task_dir / "metadata.yml").exists():
            continue
        tasks.append(Task.load(task_dir))
    return tasks


# ---------------------------------------------------------------------------
# Conditions — each builds the prompt context Claude receives.
# ---------------------------------------------------------------------------


def build_condition_baseline(task: Task) -> str:
    """Baseline: task text + source file only. No scene context at all."""
    parts = [f"# Task\n\n{task.task_text}"]
    for src in task.source_files:
        if src.exists():
            parts.append(f"\n# {src.name}\n\n```csharp\n{src.read_text(encoding='utf-8')}\n```")
    return "\n".join(parts)


def build_condition_manual_visual(task: Task) -> str:
    """Manual visual: task + source + a deterministic scene description.

    In the paper we'd hand-write these. Here we render a programmatic
    description from the graph — the upper-bound reference condition.
    """
    base = build_condition_baseline(task)
    if not task.graph_path.exists():
        return base

    graph = Graph.load(task.graph_path)
    description = _render_scene_description(graph, task.relevant_entities)
    if not description:
        return base
    return base + f"\n\n# Scene context (as if described by a developer)\n\n{description}\n"


def build_condition_unitygraph(task: Task, budget: int = 1500) -> str:
    """UnityGraph: task + source + Layer 2 injected context block."""
    from unitygraph.inject.engine import inject_context

    base = build_condition_baseline(task)
    if not task.graph_path.exists():
        return base

    graph = Graph.load(task.graph_path)
    result = inject_context(graph, task.task_text, budget=budget)
    return base + "\n\n" + result.block


def _render_scene_description(graph: Graph, entities: list[str]) -> str:
    """Produce a plain-prose scene description for the named entities."""
    nodes_by_id = graph.nodes_by_id()
    lines: list[str] = []
    for entity in entities:
        matches = [n for n in graph.nodes if str(n.data.get("name", "")).lower() == entity.lower()]
        if not matches:
            continue
        for node in matches:
            if node.type == "GameObject":
                lines.append(f"The GameObject `{node.data.get('name')}` exists in the scene.")
                comps = [
                    nodes_by_id[e.from_id].data.get("name")
                    or nodes_by_id[e.from_id].data.get("component_type")
                    for e in graph.edges
                    if e.type == "attached_to" and e.to_id == node.id and e.from_id in nodes_by_id
                ]
                if comps:
                    lines.append(f"  Its components are: {', '.join(str(c) for c in comps)}.")
                for e in graph.edges:
                    if e.type == "attached_to" and e.to_id == node.id and e.from_id in nodes_by_id:
                        script = nodes_by_id[e.from_id]
                        if script.type != "Script":
                            continue
                        inspector = e.data.get("inspector_values") or {}
                        for k, v in inspector.items():
                            if not isinstance(v, (int, float, str, bool)):
                                continue
                            lines.append(
                                f"  On {script.data.get('name')}: Inspector value `{k}` = {v}."
                            )
            elif node.type == "Script":
                fields = node.data.get("fields") or []
                for f in fields:
                    if isinstance(f, dict):
                        lines.append(
                            f"Script `{node.data.get('name')}` has a serialized field "
                            f"`{f.get('name')}` of type `{f.get('type')}` "
                            f"(code default: {f.get('default')})."
                        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class TrialScore:
    runtime_correctness: float  # 0.0 or 1.0
    component_awareness: float
    lifecycle_correctness: float
    inspector_awareness: float
    token_efficiency: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_correctness": self.runtime_correctness,
            "component_awareness": self.component_awareness,
            "lifecycle_correctness": self.lifecycle_correctness,
            "inspector_awareness": self.inspector_awareness,
            "token_efficiency": self.token_efficiency,
            "notes": list(self.notes),
        }


def score_response(task: Task, claude_output: str, injected_context_tokens: int) -> TrialScore:
    """Static scoring — no Unity runtime required.

    This is a proxy for the full spec §2.5 metric set, suitable for a local
    MVP. A paper-grade run would run the Unity Test Runner per trial.
    """
    notes: list[str] = []
    added, removed = _patch_line_sets(task.ground_truth)

    # 1. Runtime correctness (proxy): the most-changed non-comment added line
    # must substantially match the response. We compare normalized forms
    # (whitespace + comments stripped) and check the response contains ≥75%
    # of the added line's significant tokens while NOT containing the
    # removed line's distinctive literal.
    key_added = _distinctive_code_line(added)
    key_removed = _distinctive_code_line(removed)

    if key_added:
        added_tokens = _significant_tokens(key_added)
        # Signal-carrying tokens: what distinguishes added from removed.
        # If there's no removed line, every added token is signal.
        if key_removed:
            removed_tokens = set(_significant_tokens(key_removed))
            signal_tokens = [t for t in added_tokens if t not in removed_tokens]
        else:
            signal_tokens = added_tokens

        if signal_tokens:
            match_ratio = sum(1 for t in signal_tokens if _token_in_text(t, claude_output)) / len(
                signal_tokens
            )
        elif added_tokens:
            match_ratio = sum(1 for t in added_tokens if _token_in_text(t, claude_output)) / len(
                added_tokens
            )
        else:
            match_ratio = 1.0
        runtime = 1.0 if match_ratio >= 0.75 else 0.0
        notes.append(f"signal tokens: {sorted(signal_tokens)[:8]}  match: {match_ratio:.2f}")
    else:
        runtime = 1.0
        notes.append("no distinctive added line")

    # Disqualify if the distinctive removed literal is kept verbatim AND the
    # added literal is NOT present (i.e. Claude kept the wrong value).
    if key_removed and runtime == 1.0:
        removed_literal = _only_literal(key_removed)
        added_literal = _only_literal(key_added or "")
        kept_removed = bool(removed_literal and removed_literal in claude_output)
        missing_added = not added_literal or added_literal not in claude_output
        missing_signal = not signal_tokens or not any(
            _token_in_text(t, claude_output) for t in signal_tokens
        )
        if kept_removed and missing_added and missing_signal:
            runtime = 0.0
            notes.append(f"removed literal {removed_literal!r} kept without signal tokens")

    # 2. Component awareness: mentions any of the relevant entities.
    entities_mentioned = sum(1 for e in task.relevant_entities if _token_in_text(e, claude_output))
    component_awareness = (
        entities_mentioned / len(task.relevant_entities) if task.relevant_entities else 1.0
    )

    # 3. Lifecycle correctness: if the task or ground truth mentions Awake /
    # Start / Update / execution order, the response should too.
    lifecycle_kws = {"Awake", "Start", "Update", "execution order", "lifecycle"}
    needs_lifecycle = any(
        k.lower() in task.task_text.lower() or k.lower() in task.ground_truth.lower()
        for k in lifecycle_kws
    )
    lifecycle_correctness = 1.0
    if needs_lifecycle:
        lifecycle_correctness = (
            1.0 if any(k.lower() in claude_output.lower() for k in lifecycle_kws) else 0.0
        )

    # 4. Inspector awareness: if the ground truth references a field, the
    # response should too (by the same name). Especially the `requires_scene_context`
    # tasks — the whole point is that Inspector values must be discovered.
    serialized_fields = _serialized_field_names(task)
    inspector_awareness = 1.0
    if task.requires_scene_context and serialized_fields:
        hit = sum(1 for f in serialized_fields if _token_in_text(f, claude_output))
        inspector_awareness = hit / len(serialized_fields)

    # 5. Token efficiency: inverse of injected tokens, clipped. Lower injection
    # with the same correctness is better. Baseline condition has 0 injected
    # tokens so scores 1.0; unitygraph condition scales as 1 - tokens/budget.
    if injected_context_tokens <= 0:
        token_efficiency = 1.0
    else:
        token_efficiency = max(0.0, 1.0 - injected_context_tokens / 1500.0)

    return TrialScore(
        runtime_correctness=runtime,
        component_awareness=component_awareness,
        lifecycle_correctness=lifecycle_correctness,
        inspector_awareness=inspector_awareness,
        token_efficiency=token_efficiency,
        notes=notes,
    )


def _patch_line_sets(patch_text: str) -> tuple[list[str], list[str]]:
    """Split a unified diff into added and removed content lines (sans prefix)."""
    added: list[str] = []
    removed: list[str] = []
    for line in patch_text.splitlines():
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            added.append(line[1:].strip())
        elif line.startswith("-"):
            removed.append(line[1:].strip())
    return added, removed


def _token_in_text(token: str, text: str) -> bool:
    """Word-boundary presence check — ``_speed`` must not match ``_speedMultiplier``.

    We use a simple regex escape + \\b boundaries. This also avoids false
    positives when a short token happens to be a substring of a longer ID.
    """
    if not token:
        return False
    pattern = r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])"
    return re.search(pattern, text) is not None


def _distinctive_code_line(lines: list[str]) -> str | None:
    """Return the longest non-comment line from a patch hunk."""
    best = ""
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("#"):
            continue
        if len(stripped) > len(best):
            best = stripped
    return best or None


def _significant_tokens(line: str) -> list[str]:
    """Identifier / number tokens on a line, minus common keywords."""
    toks = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+\.?[0-9]*f?", line)
    skip = {
        "if",
        "else",
        "return",
        "void",
        "private",
        "public",
        "float",
        "int",
        "new",
        "var",
        "this",
        "true",
        "false",
    }
    return [t for t in toks if t not in skip and len(t) > 1]


def _only_literal(line: str) -> str | None:
    """Return a numeric literal unique to the line (for removed-literal checks)."""
    m = re.search(r"\b\d+\.\d+f?\b", line)
    return m.group(0) if m else None


def _key_tokens_from_patch(lines: list[str], opposing: list[str]) -> set[str]:
    """Extract identifier / literal tokens that are unique to ``lines`` vs ``opposing``."""
    token_re = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+\.[0-9]+f?")
    in_lines: set[str] = set()
    for line in lines:
        in_lines.update(token_re.findall(line))
    in_opposing: set[str] = set()
    for line in opposing:
        in_opposing.update(token_re.findall(line))
    unique = in_lines - in_opposing
    # Drop trivial keywords.
    skip = {
        "if",
        "else",
        "return",
        "void",
        "private",
        "public",
        "float",
        "int",
        "new",
        "var",
        "this",
    }
    return {t for t in unique if t not in skip and len(t) > 1}


def _serialized_field_names(task: Task) -> list[str]:
    """Look up `[SerializeField]` field names on scripts the task touches."""
    if not task.graph_path.exists():
        return []
    graph = Graph.load(task.graph_path)
    names: list[str] = []
    for entity in task.relevant_entities:
        for node in graph.nodes:
            if node.type == "Script" and str(node.data.get("name", "")).lower() == entity.lower():
                for f in node.data.get("fields") or []:
                    if isinstance(f, dict) and f.get("serialized") and f.get("name"):
                        names.append(str(f["name"]))
    return names


# ---------------------------------------------------------------------------
# Trial record
# ---------------------------------------------------------------------------


@dataclass
class TrialResult:
    task_id: str
    tier: int
    condition: str
    score: TrialScore
    model: str
    input_tokens: int
    output_tokens: int
    injected_context_tokens: int
    raw_response: str
    prompt_preview: str  # first 600 chars
    duration_ms: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "tier": self.tier,
            "condition": self.condition,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "injected_context_tokens": self.injected_context_tokens,
            "duration_ms": self.duration_ms,
            "score": self.score.to_dict(),
            "raw_response": self.raw_response,
            "prompt_preview": self.prompt_preview,
            "error": self.error,
        }


def dump_results(results: list[TrialResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
