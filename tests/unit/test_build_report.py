"""Unit tests for the BuildReport / BuildWarning structured warning system."""

from __future__ import annotations

from unitygraph.build.builder import BuildReport


def test_warning_tallies_group_by_category():
    report = BuildReport()
    report.warn("cs_parser", "a.cs", "boom")
    report.warn("cs_parser", "b.cs", "boom")
    report.warn("scene_parser", "a.unity", "bad yaml")
    report.warn("duplicate_node", "scope", "duplicate id")

    tallies = report.tallies()
    assert tallies["cs_parser"] == 2
    assert tallies["scene_parser"] == 1
    assert tallies["duplicate_node"] == 1


def test_empty_report_has_empty_tallies():
    report = BuildReport()
    assert report.tallies() == {}
