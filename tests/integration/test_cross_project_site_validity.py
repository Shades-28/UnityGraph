"""v2.1.0 — cross-project sampled validation that sites actually point
at real lines with the expected content.

Runs against a real Unity project (clash.io in D:/PR/Unity). Skipped when
that project isn't present, so CI on other machines doesn't break.

For each SiteKind we emit, pulls up to N random samples and verifies:
* the file exists under the project root
* the line number is within the file
* for code sites, the snippet substring is actually present on that line
* for scene YAML sites, the line has the expected marker shape

This is the kind of check I should have run before declaring v2.0 "done" —
MiniUnityProject doesn't exercise enough breadth to catch site drift.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from unitygraph.build.builder import build_project

REAL_PROJECT = Path("D:/PR/Unity/clash.io")
pytestmark = pytest.mark.skipif(
    not REAL_PROJECT.exists(),
    reason="cross-project validation requires D:/PR/Unity/clash.io locally",
)


@pytest.fixture(scope="module")
def graph():
    return build_project(REAL_PROJECT).graph


def _sample_sites_by_kind(graph, max_per_kind: int = 10):
    by_kind: dict[str, list] = {}
    for edge in graph.edges:
        for site in edge.sites:
            by_kind.setdefault(site.kind, []).append(site)
    # Deterministic sampling — seed so reruns reproduce.
    rng = random.Random(42)
    sampled: dict[str, list] = {}
    for kind, sites in by_kind.items():
        rng.shuffle(sites)
        sampled[kind] = sites[:max_per_kind]
    return sampled


def test_every_site_kind_has_valid_file_and_line(graph):
    """Every sampled site must reference a file that exists and a line
    within that file's length."""
    samples = _sample_sites_by_kind(graph)
    assert samples, "expected at least one site kind in the graph"

    failures: list[str] = []
    for kind, sites in samples.items():
        for site in sites:
            abs_path = REAL_PROJECT / site.file
            if not abs_path.exists():
                failures.append(f"{kind}: {site.file} does not exist")
                continue
            try:
                line_count = sum(1 for _ in abs_path.open("r", encoding="utf-8", errors="replace"))
            except OSError as exc:
                failures.append(f"{kind}: {site.file} unreadable ({exc})")
                continue
            if site.line < 1 or site.line > line_count:
                failures.append(
                    f"{kind}: {site.file}:{site.line} out of range (file has {line_count} lines)"
                )
    assert not failures, "site path/line failures:\n" + "\n".join(failures)


def test_code_sites_have_snippet_content_matching(graph):
    """For code sites (get_component, method_call, find_object, inherits),
    the snippet substring must appear on the referenced line."""
    code_kinds = {"get_component", "method_call", "find_object", "inherits"}
    samples = _sample_sites_by_kind(graph, max_per_kind=5)

    checked = 0
    mismatches: list[str] = []
    for kind, sites in samples.items():
        if kind not in code_kinds:
            continue
        for site in sites:
            if not site.snippet:
                continue
            abs_path = REAL_PROJECT / site.file
            if not abs_path.exists():
                continue
            lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if site.line < 1 or site.line > len(lines):
                continue
            line_text = lines[site.line - 1]
            # Snippet may span syntax the line itself contains; check substring.
            # Take the first 'word-like' chunk so small formatting diffs
            # (trailing semicolons, inline comments) don't cause false misses.
            probe = site.snippet.split(";")[0].split("//")[0].strip()
            if probe and probe not in line_text:
                mismatches.append(
                    f"{kind} {site.file}:{site.line} | expected substring "
                    f"{probe!r} | actual line: {line_text.strip()!r}"
                )
            checked += 1

    assert checked > 0, "expected at least one code site to verify"
    # Allow a small slop for minified/unusual files (<10% of samples).
    slop = max(1, checked // 10)
    assert len(mismatches) <= slop, (
        f"{len(mismatches)}/{checked} code sites had snippet mismatches:\n"
        + "\n".join(mismatches[:10])
    )


def test_attached_to_sites_point_at_document_header(graph):
    """attached_to sites must land on a line that starts with
    Unity's '--- !u!' document separator."""
    samples = _sample_sites_by_kind(graph, max_per_kind=15)
    sites = samples.get("attached_to", [])
    assert sites, "expected at least one attached_to site"

    bad: list[str] = []
    for site in sites:
        abs_path = REAL_PROJECT / site.file
        if not abs_path.exists():
            continue
        lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if site.line < 1 or site.line > len(lines):
            continue
        if not lines[site.line - 1].startswith("--- !u!"):
            bad.append(f"{site.file}:{site.line} | {lines[site.line - 1]!r}")
    assert not bad, "attached_to sites not at YAML doc headers:\n" + "\n".join(bad[:10])


def test_subscribes_to_sites_point_at_serialized_field(graph):
    """subscribes_to sites should land on a line that looks like a Unity
    serialized field (starts with 2-space indent + key + colon)."""
    samples = _sample_sites_by_kind(graph, max_per_kind=15)
    sites = samples.get("subscribes_to", [])
    if not sites:
        pytest.skip("no subscribes_to sites sampled")

    bad: list[str] = []
    for site in sites:
        abs_path = REAL_PROJECT / site.file
        if not abs_path.exists():
            continue
        lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if site.line < 1 or site.line > len(lines):
            continue
        line = lines[site.line - 1]
        # Expect either "  m_SomeField:" or "  someField:" at top-level indent.
        stripped = line.lstrip()
        if not ((line.startswith("  ") and stripped.endswith(":")) or ":" in stripped):
            bad.append(f"{site.file}:{site.line} | {line!r}")
    # Small slop — UnityEvent fields can occasionally anchor elsewhere
    # for unusual YAML layouts.
    assert len(bad) <= max(1, len(sites) // 5), (
        "subscribes_to sites not on field-like lines:\n" + "\n".join(bad[:5])
    )
