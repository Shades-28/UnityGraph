"""Tests for the `--update` / ParseCache incremental-build path."""

from __future__ import annotations

from pathlib import Path

from unitygraph.build.builder import build_project
from unitygraph.build.cache import ParseCache

FIXTURE = Path(__file__).parents[2] / "fixtures" / "MiniUnityProject"


def test_parse_cache_round_trip(tmp_path):
    cache_dir = tmp_path / "cache"
    cache = ParseCache.load(cache_dir)
    assert cache.entries == {}

    # First build populates cache.
    build_project(FIXTURE, cache=cache)
    assert cache.entries, "first build should populate cache"
    cache.write()

    # Reload: manifest persists, entries come back.
    reloaded = ParseCache.load(cache_dir)
    assert set(reloaded.entries) == set(cache.entries)

    # Second build reuses cache — graph stats must still match.
    second = build_project(FIXTURE, cache=reloaded)
    assert len(second.graph.nodes) > 0
    assert len(second.graph.edges) > 0


def test_parse_cache_invalidates_on_mtime_change(tmp_path):
    cache_dir = tmp_path / "cache"
    # Copy a single C# file so we can mutate its mtime.
    source = FIXTURE / "Assets" / "Scripts" / "PlayerController.cs"
    content = source.read_text(encoding="utf-8")

    # Work against a full copy of the fixture in tmp_path.
    import shutil

    fixture_copy = tmp_path / "mini"
    shutil.copytree(FIXTURE, fixture_copy)

    cache = ParseCache.load(cache_dir)
    build_project(fixture_copy, cache=cache)
    cache.write()

    pc = fixture_copy / "Assets" / "Scripts" / "PlayerController.cs"
    rel = str(pc.relative_to(fixture_copy))
    entry = cache.entries[rel]

    # Mutate file: change text AND touch mtime.
    pc.write_text(content + "\n// touched\n", encoding="utf-8")

    # Re-load cache (simulating a fresh CLI invocation) and re-build.
    cache2 = ParseCache.load(cache_dir)
    assert rel in cache2.entries
    build_project(fixture_copy, cache=cache2)

    # The entry for the mutated file should have a different mtime_ns now.
    new_entry = cache2.entries[rel]
    assert new_entry.mtime_ns != entry.mtime_ns
