"""UnityBench runner — drives (task, condition, model) trials through Claude.

Uses the Anthropic SDK with prompt caching on the shared system prompt, since
every trial in a run shares the same instruction block (only the per-task user
content differs). Defaults to ``claude-sonnet-4-6`` because the benchmark runs
60+ tasks x 3 conditions = 180 calls and cost is not justified by Opus for
static correctness scoring -- override with ``--model`` if needed.

Set ``ANTHROPIC_API_KEY`` before running. Without it the runner still works in
``--dry-run`` mode (prompts are built but no calls are made).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from .harness import (
    Task,
    TrialResult,
    TrialScore,
    build_condition_baseline,
    build_condition_manual_visual,
    discover_tasks,
    dump_results,
    score_response,
)

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]


CONDITIONS = ("baseline", "manual_visual", "unitygraph")

SYSTEM_PROMPT = (
    "You are an expert Unity C# developer. The user gives you a task description "
    "and the relevant source file(s). If additional scene context is included "
    "after the source, use it. Respond with the minimum necessary code changes "
    "as a unified diff (```diff fenced), and a 1-2 sentence explanation. Do not "
    "add unrelated changes.\n"
)


def build_prompt(task: Task, condition: str) -> tuple[str, int]:
    """Return (user_prompt, injected_context_tokens) for a (task, condition)."""
    if condition == "baseline":
        prompt = build_condition_baseline(task)
        return prompt, 0
    if condition == "manual_visual":
        prompt = build_condition_manual_visual(task)
        return prompt, 0  # Not counted — it's an "oracle" human proxy.
    if condition == "unitygraph":
        from unitygraph.build.graph import Graph
        from unitygraph.inject.engine import inject_context

        base = build_condition_baseline(task)
        if not task.graph_path.exists():
            return base, 0
        graph = Graph.load(task.graph_path)
        injection = inject_context(graph, task.task_text)
        return base + "\n\n" + injection.block, injection.token_count
    raise ValueError(f"unknown condition: {condition}")


def run_trial(
    client: anthropic.Anthropic | None,
    task: Task,
    condition: str,
    *,
    model: str,
    dry_run: bool = False,
) -> TrialResult:
    prompt, injected_tokens = build_prompt(task, condition)
    preview = prompt[:600]
    t_start = time.perf_counter()

    if dry_run or client is None:
        duration_ms = int((time.perf_counter() - t_start) * 1000)
        score = score_response(task, task.ground_truth, injected_tokens)
        return TrialResult(
            task_id=task.task_id,
            tier=task.tier,
            condition=condition,
            score=score,
            model=f"{model} (dry-run)",
            input_tokens=0,
            output_tokens=0,
            injected_context_tokens=injected_tokens,
            raw_response="[dry-run: no API call made]",
            prompt_preview=preview,
            duration_ms=duration_ms,
        )

    try:
        # Prompt-caching: system prompt is identical across all trials in a run.
        response = client.messages.create(
            model=model,
            max_tokens=2000,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t_start) * 1000)
        return TrialResult(
            task_id=task.task_id,
            tier=task.tier,
            condition=condition,
            score=TrialScore(0.0, 0.0, 0.0, 0.0, 0.0, notes=[f"api error: {exc}"]),
            model=model,
            input_tokens=0,
            output_tokens=0,
            injected_context_tokens=injected_tokens,
            raw_response="",
            prompt_preview=preview,
            duration_ms=duration_ms,
            error=str(exc),
        )

    duration_ms = int((time.perf_counter() - t_start) * 1000)
    text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    claude_output = "\n".join(text_blocks)
    score = score_response(task, claude_output, injected_tokens)

    return TrialResult(
        task_id=task.task_id,
        tier=task.tier,
        condition=condition,
        score=score,
        model=model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        injected_context_tokens=injected_tokens,
        raw_response=claude_output,
        prompt_preview=preview,
        duration_ms=duration_ms,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="UnityBench runner")
    parser.add_argument("--task", help="Run one specific task id (directory name)")
    parser.add_argument(
        "--condition",
        choices=CONDITIONS,
        help="Run one specific condition",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Claude model (default: claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build prompts and score against ground truth without calling Claude.",
    )
    parser.add_argument(
        "--results-dir",
        default=str(Path(__file__).parent / "results"),
        help="Where to write the jsonl results file.",
    )
    args = parser.parse_args()

    tasks = discover_tasks()
    if args.task:
        tasks = [t for t in tasks if t.task_id == args.task]
        if not tasks:
            print(f"no task matching: {args.task}", file=sys.stderr)
            return 2

    conditions = [args.condition] if args.condition else list(CONDITIONS)
    client: anthropic.Anthropic | None = None
    if not args.dry_run:
        if anthropic is None:
            print("anthropic SDK missing; install it or use --dry-run", file=sys.stderr)
            return 2
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY not set; falling back to --dry-run mode", file=sys.stderr)
            args.dry_run = True
        else:
            client = anthropic.Anthropic()

    results: list[TrialResult] = []
    for task in tasks:
        for cond in conditions:
            print(f"[run] {task.task_id:45} {cond:15} ... ", end="", flush=True)
            result = run_trial(client, task, cond, model=args.model, dry_run=args.dry_run)
            runtime = result.score.runtime_correctness
            print(
                f"runtime={runtime:.1f}  "
                f"tokens_in={result.input_tokens}  "
                f"tokens_inj={result.injected_context_tokens}  "
                f"{result.duration_ms}ms" + (f"  ERROR: {result.error}" if result.error else "")
            )
            results.append(result)

    run_id = time.strftime("%Y%m%dT%H%M%S")
    suffix = "_dry" if args.dry_run else ""
    out_path = Path(args.results_dir) / f"{run_id}{suffix}.jsonl"
    dump_results(results, out_path)
    print(f"\nwrote {len(results)} trials to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
