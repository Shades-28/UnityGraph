"""Aggregate UnityBench jsonl results into tier x condition x metric tables."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

# Windows console defaults to cp1252, which can't render some characters.
# Reconfigure stdout to UTF-8 when available so Markdown-style tables render.
if hasattr(sys.stdout, "reconfigure"):
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

METRICS = (
    "runtime_correctness",
    "component_awareness",
    "lifecycle_correctness",
    "inspector_awareness",
    "token_efficiency",
)


def _latest_results_file(results_dir: Path) -> Path | None:
    files = sorted(results_dir.glob("*.jsonl"))
    return files[-1] if files else None


def _load(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[tuple[int, str], dict[str, float]]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        key = (int(r["tier"]), r["condition"])
        grouped[key].append(r["score"])

    summary: dict[tuple[int, str], dict[str, float]] = {}
    for key, scores in grouped.items():
        summary[key] = {m: round(mean(s[m] for s in scores), 3) for m in METRICS}
        summary[key]["n"] = len(scores)  # type: ignore[assignment]
    return summary


def _format_table(summary: dict[tuple[int, str], dict[str, float]], tiers: list[int]) -> str:
    conditions = ("baseline", "manual_visual", "unitygraph")
    lines: list[str] = []

    for metric in METRICS:
        lines.append(f"\n## {metric}")
        header = f"| Tier | {' | '.join(conditions)} | Delta (ug - baseline) |"
        sep = "|---" + "---|" * (len(conditions) + 1)
        lines.append(header)
        lines.append(sep)
        for tier in tiers:
            row = [f"Tier {tier}"]
            vals: dict[str, float] = {}
            for cond in conditions:
                val = summary.get((tier, cond), {}).get(metric)
                vals[cond] = val if isinstance(val, (int, float)) else 0.0
                row.append(f"{val:.3f}" if val is not None else "—")
            delta = vals["unitygraph"] - vals["baseline"]
            row.append(f"{delta:+.3f}")
            lines.append("| " + " | ".join(row) + " |")

    # Headline claim: Tier 2 runtime correctness improvement.
    tier2_baseline = summary.get((2, "baseline"), {}).get("runtime_correctness", 0.0)
    tier2_ug = summary.get((2, "unitygraph"), {}).get("runtime_correctness", 0.0)
    delta_t2 = tier2_ug - tier2_baseline
    pct = (tier2_ug / tier2_baseline - 1.0) * 100 if tier2_baseline else 0.0
    lines.append("\n## Headline")
    lines.append(
        f"Tier 2 runtime correctness: baseline={tier2_baseline:.3f}, "
        f"unitygraph={tier2_ug:.3f} (Delta={delta_t2:+.3f}, {pct:+.1f}%)"
    )
    if tier2_baseline > 0 and pct >= 30.0:
        lines.append("Plan §I5 gate: PASS (≥30% improvement on Tier 2)")
    elif tier2_baseline == 0 and tier2_ug > 0:
        lines.append("Plan §I5 gate: PASS (non-zero Tier 2 improvement from zero baseline)")
    else:
        lines.append("Plan §I5 gate: FAIL (<30% improvement)")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="UnityBench report")
    parser.add_argument("results_file", nargs="?", help="Specific jsonl file to summarize")
    parser.add_argument(
        "--dir",
        default=str(Path(__file__).parent / "results"),
        help="Results directory (uses the latest file if no file given)",
    )
    args = parser.parse_args()

    if args.results_file:
        path = Path(args.results_file)
    else:
        path = _latest_results_file(Path(args.dir))
        if path is None:
            print("no results found", flush=True)
            return 1

    rows = _load(path)
    summary = summarize(rows)
    tiers = sorted({k[0] for k in summary})
    print(f"# UnityBench report — {path.name}\n")
    print(f"N trials: {len(rows)}")
    print(_format_table(summary, tiers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
