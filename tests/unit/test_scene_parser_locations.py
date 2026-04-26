"""v1.5.0 -- scene parser captures file-level line numbers on UnityEvent
persistent calls, Inspector values, and prefab overrides.
"""

from __future__ import annotations

from pathlib import Path

from unitygraph.build.parsers import scene_parser
from unitygraph.build.parsers.unity_yaml import UnityDoc, load_documents

FIXTURE_SCENE = (
    Path(__file__).parents[2] / "fixtures" / "MiniUnityProject" / "Assets" / "Scenes" / "Main.unity"
)


def test_unitydoc_header_line_matches_file() -> None:
    text = FIXTURE_SCENE.read_text(encoding="utf-8")
    docs = load_documents(text)
    assert docs, "expected documents"
    # Every header_line must be >= 1 and correspond to an actual --- line.
    raw_lines = text.splitlines()
    for doc in docs:
        assert doc.header_line >= 1
        assert raw_lines[doc.header_line - 1].startswith("---")


def test_find_key_line_points_at_top_level_field() -> None:
    text = FIXTURE_SCENE.read_text(encoding="utf-8")
    docs = load_documents(text)
    ui_button = next(d for d in docs if d.file_id == 500002)
    # m_OnClick is a top-level serialized field of the MonoBehaviour.
    line = ui_button.find_key_line("m_OnClick")
    raw_lines = text.splitlines()
    assert raw_lines[line - 1].strip().startswith("m_OnClick")


def test_event_connection_carries_line_number() -> None:
    scene = scene_parser.parse_file(FIXTURE_SCENE)
    ui_button = next(c for c in scene.components if c.file_id == 500002)
    assert ui_button.event_connections, "UI_Button should wire m_OnClick"
    ec = ui_button.event_connections[0]
    assert ec.field_name == "m_OnClick"
    assert ec.method_name == "OnAttackPressed"
    assert ec.line > 0
    # The line must point at the m_OnClick field in the scene file.
    raw_lines = FIXTURE_SCENE.read_text(encoding="utf-8").splitlines()
    assert "m_OnClick" in raw_lines[ec.line - 1]


def test_component_header_line_is_set() -> None:
    scene = scene_parser.parse_file(FIXTURE_SCENE)
    for comp in scene.components:
        assert comp.header_line > 0, f"component {comp.file_id} has no header_line"


def test_inspector_value_lines_populated_for_monobehaviour() -> None:
    scene = scene_parser.parse_file(FIXTURE_SCENE)
    # PlayerController (script_guid) on Player has _maxHealth inspector override.
    pc = next(
        c
        for c in scene.components
        if c.script_guid and "_maxHealth" in c.inspector_values
    )
    # Every inspector key we kept should have a line (non-zero) or not -- but
    # at least the top-level keys should resolve.
    assert pc.inspector_value_lines, "expected at least one inspector_value_line"
    for _key, line in pc.inspector_value_lines.items():
        assert line > 0


def test_find_key_line_returns_zero_for_missing_key() -> None:
    doc = UnityDoc(
        class_id=114,
        file_id=1,
        type_name="MonoBehaviour",
        body={"a": 1},
        header_line=10,
        body_text="\nMonoBehaviour:\n  a: 1\n",
    )
    assert doc.find_key_line("nonexistent") == 0
