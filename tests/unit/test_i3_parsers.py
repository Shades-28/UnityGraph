"""Unit tests for Animator / ShaderGraph parsers on real external files."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from unitygraph.build.parsers import animator_parser, shadergraph_parser

EXTERNAL_ROOT = Path(os.environ.get("UNITYGRAPH_EXTERNAL_ROOT", "D:/PR/Unity"))

ENEMY_ANIMATOR = (
    EXTERNAL_ROOT
    / "clash.io"
    / "Assets"
    / "_Assets"
    / "Prefab"
    / "Characters"
    / "Enemy"
    / "Enemy_Animator.controller"
)
TMP_SHADER = (
    EXTERNAL_ROOT
    / "my-cloths-empire"
    / "Assets"
    / "TextMesh Pro"
    / "Shaders"
    / "TMP_SDF-URP Lit.shadergraph"
)


@pytest.mark.skipif(not ENEMY_ANIMATOR.exists(), reason="external Enemy_Animator not found")
def test_animator_parser_extracts_states_and_parameters():
    parsed = animator_parser.parse_file(ENEMY_ANIMATOR)
    assert parsed.controller_name == "Enemy_Animator"
    assert {s.name for s in parsed.states} == {"Idle", "Attack", "Move"}
    assert parsed.parameters, "expected at least one animator parameter"
    assert any(p.name == "Velocity" for p in parsed.parameters)
    assert parsed.layers
    assert parsed.layers[0].state_machine_file_id is not None


@pytest.mark.skipif(not TMP_SHADER.exists(), reason="external TMP shadergraph not found")
def test_shadergraph_parser_extracts_properties():
    parsed = shadergraph_parser.parse_file(TMP_SHADER)
    assert parsed.name.startswith("TMP_SDF")
    # TMP shader has dozens of shader properties.
    assert len(parsed.properties) > 10
    assert parsed.output_slots
