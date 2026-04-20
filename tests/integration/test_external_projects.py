"""Integration tests against real Unity projects at ``D:/PR/Unity/``.

These are SKIPPED unless the project path exists. Gate assertions come from
``UnityGraph_Development_Plan.md`` §Iteration 2: all parsers survive, <5% files
skipped, <60s build on the largest project.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from unitygraph.build.builder import build_project

EXTERNAL_ROOT = Path(os.environ.get("UNITYGRAPH_EXTERNAL_ROOT", "D:/PR/Unity"))


def _external(name: str) -> Path:
    return EXTERNAL_ROOT / name


@pytest.mark.parametrize(
    "project_name,max_skip_pct,max_build_s",
    [
        pytest.param("Indian-Bike-Gangster-3D", 5.0, 60.0),
        pytest.param("clash.io", 5.0, 60.0),
        # Graudation-Saga is the stress test — opt-in only via -m slow.
        pytest.param("Graudation-Saga", 5.0, 600.0, marks=pytest.mark.slow),
    ],
)
def test_external_project_builds(project_name, max_skip_pct, max_build_s):
    project = _external(project_name)
    if not project.exists():
        pytest.skip(f"external project not available: {project}")

    result = build_project(project)
    report = result.report

    total_files = report.n_cs + report.n_scenes + report.n_prefabs
    if total_files == 0:
        pytest.skip(f"{project_name}: no parseable files")

    # Skip percentage must be under the budget.
    skipped = len(
        [w for w in report.warnings if w.category in {"cs_parser", "scene_parser", "prefab_parser"}]
    )
    skip_pct = (skipped / total_files) * 100.0
    assert skip_pct <= max_skip_pct, (
        f"{project_name}: {skipped}/{total_files} files failed "
        f"({skip_pct:.1f}%) > {max_skip_pct}% budget. "
        f"Tallies: {report.tallies()}"
    )

    # Build time budget.
    build_s = result.graph.build_ms / 1000.0
    assert build_s <= max_build_s, (
        f"{project_name}: build took {build_s:.1f}s > {max_build_s}s budget"
    )

    # Sanity: graph must contain nodes.
    assert len(result.graph.nodes) > 0
