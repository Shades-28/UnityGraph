"""Animator Controller parser.

A ``.controller`` file is a single Unity YAML document collection containing:

- ``AnimatorController`` (classID 91) -- top-level, with ``m_AnimatorParameters``
  and ``m_AnimatorLayers``. Each layer references a ``m_StateMachine`` by
  fileID.
- ``AnimatorStateMachine`` (classID 1107) -- has ``m_ChildStates``,
  ``m_AnyStateTransitions``, ``m_EntryTransitions``, ``m_DefaultState``.
- ``AnimatorState`` (classID 1102) -- has ``m_Name``, ``m_Motion``, and
  ``m_Transitions``.
- ``AnimatorStateTransition`` (classID 1101) -- has ``m_DstState``,
  ``m_Conditions``, ``m_TransitionDuration``, ``m_CanTransitionToSelf``.
- ``BlendTree`` (classID 206) -- a motion type referenced by states; contains
  child motions keyed off an ``m_BlendParameter``.

Parameter types:
  0 = Float, 1 = Int, 2 = Bool, 3 = Trigger (new in 2019), 9 = Trigger (legacy)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .unity_yaml import UnityDoc, load_documents

ANIMATOR_CONTROLLER_CLASS_ID = 91
ANIMATOR_STATE_CLASS_ID = 1102
ANIMATOR_STATE_MACHINE_CLASS_ID = 1107
ANIMATOR_STATE_TRANSITION_CLASS_ID = 1101

# We need Animator-specific class IDs, so bypass the scene-parser class filter.
_ANIMATOR_CLASS_FILTER: frozenset[int] = frozenset(
    {
        91,  # AnimatorController
        206,  # BlendTree
        1101,  # AnimatorStateTransition
        1102,  # AnimatorState
        1107,  # AnimatorStateMachine
    }
)

_PARAM_TYPE_NAMES: dict[int, str] = {
    0: "Float",
    1: "Int",
    2: "Bool",
    3: "Trigger",
    9: "Trigger",
}


@dataclass
class AnimatorParameter:
    name: str
    type_name: str
    default: float | int | bool


@dataclass
class AnimatorStateInfo:
    file_id: int
    name: str
    motion_file_id: int | None = None
    motion_guid: str | None = None


@dataclass
class AnimatorTransition:
    source_state_file_id: int
    dest_state_file_id: int | None
    conditions: list[dict[str, Any]] = field(default_factory=list)
    has_exit_time: bool = False
    duration: float = 0.0


@dataclass
class AnimatorLayer:
    name: str
    state_machine_file_id: int | None


@dataclass
class ParsedAnimator:
    path: Path
    controller_name: str
    parameters: list[AnimatorParameter] = field(default_factory=list)
    layers: list[AnimatorLayer] = field(default_factory=list)
    states: list[AnimatorStateInfo] = field(default_factory=list)
    transitions: list[AnimatorTransition] = field(default_factory=list)


def parse_file(path: Path) -> ParsedAnimator:
    text = path.read_text(encoding="utf-8", errors="replace")
    docs = load_documents(text, class_filter=_ANIMATOR_CLASS_FILTER)

    result = ParsedAnimator(path=path, controller_name=path.stem)
    transitions_by_fileid: dict[int, UnityDoc] = {}
    states: dict[int, UnityDoc] = {}

    for doc in docs:
        if doc.class_id == ANIMATOR_CONTROLLER_CLASS_ID:
            _ingest_controller(result, doc)
        elif doc.class_id == ANIMATOR_STATE_CLASS_ID:
            states[doc.file_id] = doc
        elif doc.class_id == ANIMATOR_STATE_TRANSITION_CLASS_ID:
            transitions_by_fileid[doc.file_id] = doc

    # State parsing: need the full state list first so we can resolve transition
    # source states (each transition lives inside a state's m_Transitions list,
    # but in YAML each transition is a separate top-level document referenced
    # by fileID).
    for fid, sdoc in states.items():
        result.states.append(
            AnimatorStateInfo(
                file_id=fid,
                name=str(sdoc.body.get("m_Name", "")) or f"State_{fid}",
                motion_file_id=_ref_fileid(sdoc.body.get("m_Motion")),
                motion_guid=_ref_guid(sdoc.body.get("m_Motion")),
            )
        )
        for t_ref in sdoc.body.get("m_Transitions", []) or []:
            tfid = t_ref.get("fileID") if isinstance(t_ref, dict) else None
            if not isinstance(tfid, int):
                continue
            tdoc = transitions_by_fileid.get(tfid)
            if tdoc is None:
                continue
            result.transitions.append(
                AnimatorTransition(
                    source_state_file_id=fid,
                    dest_state_file_id=_ref_fileid(tdoc.body.get("m_DstState")),
                    conditions=_parse_conditions(tdoc.body.get("m_Conditions") or []),
                    has_exit_time=bool(tdoc.body.get("m_HasExitTime", False)),
                    duration=float(tdoc.body.get("m_TransitionDuration", 0.0) or 0.0),
                )
            )

    return result


def _ingest_controller(result: ParsedAnimator, doc: UnityDoc) -> None:
    if doc.body.get("m_Name"):
        result.controller_name = str(doc.body["m_Name"])

    for entry in doc.body.get("m_AnimatorParameters", []) or []:
        if not isinstance(entry, dict):
            continue
        type_num = int(entry.get("m_Type", 0) or 0)
        type_name = _PARAM_TYPE_NAMES.get(type_num, f"Type{type_num}")
        default: float | int | bool
        if type_name == "Float":
            default = float(entry.get("m_DefaultFloat", 0.0) or 0.0)
        elif type_name in {"Int", "Trigger"}:
            default = int(entry.get("m_DefaultInt", 0) or 0)
        else:
            default = bool(int(entry.get("m_DefaultBool", 0) or 0))
        result.parameters.append(
            AnimatorParameter(
                name=str(entry.get("m_Name", "")),
                type_name=type_name,
                default=default,
            )
        )

    for entry in doc.body.get("m_AnimatorLayers", []) or []:
        if not isinstance(entry, dict):
            continue
        result.layers.append(
            AnimatorLayer(
                name=str(entry.get("m_Name", "")),
                state_machine_file_id=_ref_fileid(entry.get("m_StateMachine")),
            )
        )


def _ref_fileid(ref: Any) -> int | None:
    if isinstance(ref, dict):
        fid = ref.get("fileID")
        if isinstance(fid, int) and fid != 0:
            return fid
    return None


def _ref_guid(ref: Any) -> str | None:
    if isinstance(ref, dict):
        guid = ref.get("guid")
        if guid:
            return str(guid)
    return None


def _parse_conditions(raw: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        out.append(
            {
                "mode": int(c.get("m_ConditionMode", 0) or 0),
                "parameter": str(c.get("m_ConditionEvent", "")),
                "threshold": c.get("m_EventTreshold") or c.get("m_EventThreshold") or 0,
            }
        )
    return out
