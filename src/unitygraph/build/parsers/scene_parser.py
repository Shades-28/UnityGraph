"""Scene/prefab parser.

A Unity ``.unity`` or ``.prefab`` file is a collection of ``---``-separated
documents (``UnityDoc`` — see ``unity_yaml.py``). We care about three kinds:

1. ``GameObject`` (classID 1) — has a name, tag, layer, active flag, and a
   ``m_Component`` list referencing fileIDs on the same document.
2. Any classID whose body has ``m_GameObject: {fileID: N}`` — a component
   attached to GameObject ``N``. This covers built-in components (``Transform``,
   ``Rigidbody``, ``BoxCollider``, ...) and ``MonoBehaviour`` scripts.
3. ``MonoBehaviour`` (classID 114) specifically — its ``m_Script: {guid: X}``
   tells us which user script class this component represents.

Prefab variants (``PrefabInstance``, classID 1001) produce ``m_Modifications``
override entries — we record the raw list for I3 to consume later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .unity_yaml import UnityDoc, load_documents

# Unity classID → friendly component-type name for the graph.
BUILTIN_COMPONENT_TYPES: dict[int, str] = {
    4: "Transform",
    20: "Camera",
    33: "MeshFilter",
    54: "Rigidbody",
    64: "MeshCollider",
    65: "BoxCollider",
    82: "AudioSource",
    92: "Behaviour",
    95: "Animator",
    102: "TextMesh",
    111: "Animation",
    135: "SphereCollider",
    136: "CapsuleCollider",
    137: "SkinnedMeshRenderer",
    143: "CharacterController",
    146: "CharacterJoint",
    154: "TerrainCollider",
    161: "Terrain",
    195: "NavMeshAgent",
    198: "ParticleSystem",
    199: "ParticleSystemRenderer",
    210: "SortingGroup",
    212: "SpriteRenderer",
    224: "RectTransform",
    330: "LODGroup",
}

SCRIPT_CLASS_ID = 114
GAMEOBJECT_CLASS_ID = 1
PREFAB_INSTANCE_CLASS_ID = 1001


@dataclass
class SceneGameObject:
    file_id: int
    name: str
    tag: str
    layer: int
    is_active: bool
    component_file_ids: list[int] = field(default_factory=list)
    parent_transform_file_id: int | None = None


@dataclass
class SceneComponent:
    file_id: int
    class_id: int
    type_name: str  # e.g. "Transform", "Rigidbody", "MonoBehaviour"
    gameobject_file_id: int | None
    inspector_values: dict[str, Any] = field(default_factory=dict)
    script_guid: str | None = None  # only for MonoBehaviour
    event_connections: list[EventConnection] = field(default_factory=list)


@dataclass
class EventConnection:
    """A persistent UnityEvent listener found on a MonoBehaviour."""

    field_name: str  # the serialized field name holding the UnityEvent (e.g., "m_OnClick")
    target_file_id: int
    method_name: str
    argument_mode: int
    target_type: str | None = None  # "m_TargetAssemblyTypeName"


@dataclass
class PrefabOverride:
    target_file_id: int
    property_path: str
    value: Any


@dataclass
class PrefabInstanceInfo:
    file_id: int
    source_prefab_guid: str | None = None
    overrides: list[PrefabOverride] = field(default_factory=list)


@dataclass
class ParsedScene:
    """Result of parsing one ``.unity`` or ``.prefab`` file."""

    path: Path
    gameobjects: list[SceneGameObject] = field(default_factory=list)
    components: list[SceneComponent] = field(default_factory=list)
    prefab_instances: list[PrefabInstanceInfo] = field(default_factory=list)

    # Convenience lookups (populated at parse time)
    gameobjects_by_fileid: dict[int, SceneGameObject] = field(default_factory=dict)
    components_by_fileid: dict[int, SceneComponent] = field(default_factory=dict)


_EVENT_FIELD_MARKERS = frozenset({"m_PersistentCalls"})


def parse_file(path: Path) -> ParsedScene:
    """Parse ``path`` (a .unity or .prefab file) into a ``ParsedScene``."""
    text = path.read_text(encoding="utf-8", errors="replace")
    docs = load_documents(text)

    scene = ParsedScene(path=path)
    for doc in docs:
        if doc.class_id == GAMEOBJECT_CLASS_ID:
            _ingest_gameobject(scene, doc)
        elif doc.class_id == PREFAB_INSTANCE_CLASS_ID:
            _ingest_prefab_instance(scene, doc)
        else:
            _ingest_component(scene, doc)

    # Second pass: resolve parent transform for each GameObject via its Transform.
    for go in scene.gameobjects:
        for comp_id in go.component_file_ids:
            comp = scene.components_by_fileid.get(comp_id)
            if comp is None or comp.class_id != 4:
                continue
            father = comp.inspector_values.get("m_Father")
            if isinstance(father, dict):
                father_fid = father.get("fileID")
                if isinstance(father_fid, int) and father_fid != 0:
                    go.parent_transform_file_id = father_fid
            break

    return scene


def _ingest_gameobject(scene: ParsedScene, doc: UnityDoc) -> None:
    name = str(doc.body.get("m_Name", "")) or f"GameObject_{doc.file_id}"
    tag = str(doc.body.get("m_TagString", "Untagged"))
    layer = int(doc.body.get("m_Layer", 0) or 0)
    is_active = bool(int(doc.body.get("m_IsActive", 1) or 0))

    component_ids: list[int] = []
    for entry in doc.body.get("m_Component", []) or []:
        # entry := {component: {fileID: N}}
        if not isinstance(entry, dict):
            continue
        ref = entry.get("component")
        if isinstance(ref, dict):
            fid = ref.get("fileID")
            if isinstance(fid, int):
                component_ids.append(fid)

    go = SceneGameObject(
        file_id=doc.file_id,
        name=name,
        tag=tag,
        layer=layer,
        is_active=is_active,
        component_file_ids=component_ids,
    )
    scene.gameobjects.append(go)
    scene.gameobjects_by_fileid[doc.file_id] = go


def _ingest_component(scene: ParsedScene, doc: UnityDoc) -> None:
    gameobject_ref = doc.body.get("m_GameObject")
    go_fid: int | None = None
    if isinstance(gameobject_ref, dict):
        raw = gameobject_ref.get("fileID")
        if isinstance(raw, int) and raw != 0:
            go_fid = raw

    type_name = BUILTIN_COMPONENT_TYPES.get(doc.class_id, doc.type_name)

    comp = SceneComponent(
        file_id=doc.file_id,
        class_id=doc.class_id,
        type_name=type_name,
        gameobject_file_id=go_fid,
    )

    if doc.class_id == SCRIPT_CLASS_ID:
        script_ref = doc.body.get("m_Script")
        if isinstance(script_ref, dict):
            guid = script_ref.get("guid")
            comp.script_guid = str(guid) if guid else None
        # Everything else on a MonoBehaviour body is user-authored Inspector data.
        inspector = {
            k: v
            for k, v in doc.body.items()
            if k
            not in {
                "m_ObjectHideFlags",
                "m_CorrespondingSourceObject",
                "m_PrefabInstance",
                "m_PrefabAsset",
                "m_GameObject",
                "m_Enabled",
                "m_EditorHideFlags",
                "m_Script",
                "m_Name",
                "m_EditorClassIdentifier",
            }
        }
        comp.inspector_values = inspector
        comp.event_connections = _extract_event_connections(inspector)
    else:
        # For built-in components, keep the body as-is minus boilerplate.
        inspector = {
            k: v
            for k, v in doc.body.items()
            if k not in {"m_ObjectHideFlags", "m_GameObject", "m_Enabled", "serializedVersion"}
        }
        comp.inspector_values = inspector

    scene.components.append(comp)
    scene.components_by_fileid[doc.file_id] = comp


def _ingest_prefab_instance(scene: ParsedScene, doc: UnityDoc) -> None:
    source_ref = doc.body.get("m_SourcePrefab") or doc.body.get("m_ParentPrefab")
    source_guid: str | None = None
    if isinstance(source_ref, dict):
        guid = source_ref.get("guid")
        source_guid = str(guid) if guid else None

    overrides: list[PrefabOverride] = []
    mods = doc.body.get("m_Modification") or {}
    for mod in mods.get("m_Modifications", []) or []:
        if not isinstance(mod, dict):
            continue
        target = mod.get("target", {})
        target_fid = target.get("fileID") if isinstance(target, dict) else None
        if not isinstance(target_fid, int):
            continue
        overrides.append(
            PrefabOverride(
                target_file_id=target_fid,
                property_path=str(mod.get("propertyPath", "")),
                value=mod.get("value"),
            )
        )

    scene.prefab_instances.append(
        PrefabInstanceInfo(
            file_id=doc.file_id,
            source_prefab_guid=source_guid,
            overrides=overrides,
        )
    )


def _extract_event_connections(values: dict[str, Any]) -> list[EventConnection]:
    """Walk MonoBehaviour field values for UnityEvent persistent calls."""
    connections: list[EventConnection] = []
    for field_name, value in values.items():
        _walk_for_events(field_name, value, connections)
    return connections


def _walk_for_events(field_name: str, value: Any, out: list[EventConnection]) -> None:
    if isinstance(value, dict):
        if "m_PersistentCalls" in value:
            persistent = value["m_PersistentCalls"]
            if isinstance(persistent, dict):
                calls = persistent.get("m_Calls", []) or []
                for call in calls:
                    if not isinstance(call, dict):
                        continue
                    target = call.get("m_Target", {})
                    target_fid = target.get("fileID") if isinstance(target, dict) else None
                    if not isinstance(target_fid, int) or target_fid == 0:
                        continue
                    out.append(
                        EventConnection(
                            field_name=field_name,
                            target_file_id=target_fid,
                            method_name=str(call.get("m_MethodName", "")),
                            argument_mode=int(call.get("m_Mode", 0) or 0),
                            target_type=call.get("m_TargetAssemblyTypeName"),
                        )
                    )
            return
        for k, v in value.items():
            _walk_for_events(f"{field_name}.{k}", v, out)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _walk_for_events(f"{field_name}[{i}]", item, out)
