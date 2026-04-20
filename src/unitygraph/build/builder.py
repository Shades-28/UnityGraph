"""Builder — orchestrates parsers, emits ``graph.json``.

Algorithm:

1. Walk the project for ``.cs``, ``.unity``, ``.prefab``, and the
   ``MonoManager.asset`` file.
2. Run each parser. Accumulate raw results keyed by file.
3. Build a ``guid → Path`` index from all ``.meta`` files. This lets us
   resolve ``MonoBehaviour.m_Script.guid`` references to concrete
   ``ParsedScript`` entries.
4. Emit nodes:
   * one ``Script`` node per C# class (both ``MonoBehaviour`` and plain)
   * one ``Scene`` node per ``.unity`` file
   * one ``Prefab`` node per ``.prefab`` file
   * one ``GameObject`` node per scene/prefab GameObject
   * one ``Component`` node per non-script component; MonoBehaviour
     components point at their Script node instead (``attached_to`` edge
     from Script node to GameObject).
5. Emit edges: ``attached_to``, ``co_exists_with``, ``depends_on``
   (GetComponent<T>), ``inherits``, ``subscribes_to``, ``loads_scene``.

The builder never crashes on a malformed file — errors are collected into
``BuildReport.warnings`` and the build continues.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .graph import (
    Edge,
    Graph,
    Node,
    make_component_id,
    make_gameobject_id,
    make_prefab_id,
    make_scene_id,
    make_script_id,
)
from .parsers import cs_parser, execorder_parser, meta_parser, scene_parser
from .parsers.scene_parser import SCRIPT_CLASS_ID, ParsedScene


@dataclass
class BuildReport:
    n_cs: int = 0
    n_scenes: int = 0
    n_prefabs: int = 0
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


@dataclass
class BuildResult:
    graph: Graph
    report: BuildReport


def build_project(project_root: Path) -> BuildResult:
    start = time.perf_counter()
    graph = Graph(project_root=str(project_root.resolve()))
    report = BuildReport()

    # 1. Discover asset files.
    cs_files = _discover(project_root, "*.cs", skip_generated=True)
    scene_files = _discover(project_root, "*.unity", skip_generated=True)
    prefab_files = _discover(project_root, "*.prefab", skip_generated=True)

    report.n_cs = len(cs_files)
    report.n_scenes = len(scene_files)
    report.n_prefabs = len(prefab_files)

    # 2. guid -> asset path (for script ref resolution).
    guid_index = meta_parser.build_guid_index(project_root)

    # 3. Parse C# scripts. Map guid -> first class in file (Unity convention).
    script_class_by_guid: dict[str, tuple[cs_parser.ClassInfo, Path]] = {}
    parsed_scripts: list[tuple[Path, list[cs_parser.ClassInfo]]] = []
    for path in cs_files:
        try:
            parsed = cs_parser.parse_file(path)
        except Exception as exc:  # noqa: BLE001 — parsing must never crash the build
            report.warn(f"cs_parser failed on {path}: {exc}")
            continue
        parsed_scripts.append((path, parsed.classes))
        meta = path.with_suffix(path.suffix + ".meta")
        guid = meta_parser.load_meta_guid(meta) if meta.exists() else None
        if guid and parsed.classes:
            # Unity convention: first class with the filename is *the* script.
            primary = next((c for c in parsed.classes if c.name == path.stem), parsed.classes[0])
            script_class_by_guid[guid] = (primary, path)

    # 4. Emit Script nodes.
    for path, classes in parsed_scripts:
        rel = str(path.relative_to(project_root))
        for klass in classes:
            node = Node(
                id=make_script_id(klass.name, rel),
                type="Script",
                data={
                    "name": klass.name,
                    "namespace": klass.namespace,
                    "file_path": rel,
                    "script_type": _script_type(klass),
                    **klass.to_dict(),
                },
            )
            graph.add_node(node)
            if klass.base_class and klass.base_class not in {
                "MonoBehaviour",
                "ScriptableObject",
                "object",
            }:
                # We can only link to known user classes; foreign bases become
                # a trailing attribute rather than a real edge. If the base
                # class is a user script (by name), emit the edge.
                base_id = _find_script_id_by_name(graph, klass.base_class)
                if base_id is not None:
                    graph.add_edge(Edge(from_id=node.id, to_id=base_id, type="inherits"))
            # depends_on edges for GetComponent<T>
            for t in klass.get_component_types:
                target_id = _find_script_id_by_name(graph, t)
                if target_id is not None:
                    graph.add_edge(
                        Edge(
                            from_id=node.id,
                            to_id=target_id,
                            type="depends_on",
                            data={"via": "GetComponent", "target_type": t},
                        )
                    )

    # 5. Parse scenes + prefabs, emit GameObject / Component nodes and attach edges.
    for scene_path in scene_files:
        try:
            scene_parsed = scene_parser.parse_file(scene_path)
        except Exception as exc:  # noqa: BLE001
            report.warn(f"scene_parser failed on {scene_path}: {exc}")
            continue
        scene_id = make_scene_id(scene_path.stem)
        graph.add_node(
            Node(
                id=scene_id,
                type="Scene",
                data={
                    "name": scene_path.stem,
                    "file_path": str(scene_path.relative_to(project_root)),
                },
            )
        )
        _ingest_scene(graph, scene_id, scene_parsed, script_class_by_guid, guid_index, report)

    for prefab_path in prefab_files:
        try:
            prefab_parsed = scene_parser.parse_file(prefab_path)
        except Exception as exc:  # noqa: BLE001
            report.warn(f"scene_parser failed on {prefab_path}: {exc}")
            continue
        prefab_id = make_prefab_id(prefab_path.stem)
        graph.add_node(
            Node(
                id=prefab_id,
                type="Prefab",
                data={
                    "name": prefab_path.stem,
                    "file_path": str(prefab_path.relative_to(project_root)),
                },
            )
        )
        _ingest_scene(graph, prefab_id, prefab_parsed, script_class_by_guid, guid_index, report)

    # 6. Parse execution order → annotate Script nodes.
    exec_order_path = project_root / "ProjectSettings" / "MonoManager.asset"
    exec_entries = execorder_parser.parse_file(exec_order_path)
    order_by_guid = {e.guid: e.order for e in exec_entries}
    for node in graph.nodes:
        if node.type != "Script":
            continue
        # Find the guid for this script node by reverse lookup.
        for guid, (klass, path) in script_class_by_guid.items():
            rel = str(path.relative_to(project_root))
            if node.id == make_script_id(klass.name, rel):
                if guid in order_by_guid:
                    node.data["execution_order"] = order_by_guid[guid]
                break

    graph.build_ms = int((time.perf_counter() - start) * 1000)
    return BuildResult(graph=graph, report=report)


def _discover(root: Path, pattern: str, *, skip_generated: bool) -> list[Path]:
    out: list[Path] = []
    skip_dirs = {"Library", "Temp", "obj", "Build", "Builds", "Logs"}
    for path in root.rglob(pattern):
        parts = set(path.parts)
        if skip_generated and parts & skip_dirs:
            continue
        out.append(path)
    return out


def _script_type(klass: cs_parser.ClassInfo) -> str:
    if klass.is_monobehaviour:
        return "MonoBehaviour"
    if klass.is_scriptable_object:
        return "ScriptableObject"
    return "Class"


def _find_script_id_by_name(graph: Graph, class_name: str) -> str | None:
    for node in graph.nodes:
        if node.type == "Script" and node.data.get("name") == class_name:
            return node.id
    return None


def _ingest_scene(
    graph: Graph,
    scope_id: str,
    parsed: ParsedScene,
    script_class_by_guid: dict[str, tuple[cs_parser.ClassInfo, Path]],
    guid_index: dict[str, Path],
    report: BuildReport,
) -> None:
    # Emit GameObject nodes.
    go_id_by_fileid: dict[int, str] = {}
    for go in parsed.gameobjects:
        gid = make_gameobject_id(scope_id, go.file_id, go.name)
        go_id_by_fileid[go.file_id] = gid
        graph.add_node(
            Node(
                id=gid,
                type="GameObject",
                data={
                    "name": go.name,
                    "scope": scope_id,
                    "tag": go.tag,
                    "layer": go.layer,
                    "is_active": go.is_active,
                    "file_id": go.file_id,
                },
            )
        )

    # Emit Component nodes + attached_to edges.
    # Track MonoBehaviour fileID -> Script node id for event connection edges.
    mb_fileid_to_script_id: dict[int, str] = {}
    for comp in parsed.components:
        if comp.gameobject_file_id is None:
            continue
        owner_id = go_id_by_fileid.get(comp.gameobject_file_id)
        if owner_id is None:
            continue

        if comp.class_id == SCRIPT_CLASS_ID and comp.script_guid:
            script_entry = script_class_by_guid.get(comp.script_guid)
            if script_entry is None:
                # Unknown script guid — maybe a third-party package script.
                # Record a placeholder Script node so Inspector values are still queryable.
                ext_rel = str(guid_index.get(comp.script_guid) or f"<external:{comp.script_guid}>")
                unknown_name = Path(ext_rel).stem if ext_rel.endswith(".cs") else f"UnknownScript_{comp.script_guid[:8]}"
                placeholder_id = make_script_id(unknown_name, ext_rel)
                if not graph.has_node(placeholder_id):
                    graph.add_node(
                        Node(
                            id=placeholder_id,
                            type="Script",
                            data={
                                "name": unknown_name,
                                "file_path": ext_rel,
                                "script_type": "MonoBehaviour",
                                "external": True,
                                "guid": comp.script_guid,
                            },
                        )
                    )
                script_node_id = placeholder_id
            else:
                klass, path = script_entry
                rel = str(path.relative_to(Path(graph.project_root)))
                script_node_id = make_script_id(klass.name, rel)

            mb_fileid_to_script_id[comp.file_id] = script_node_id
            graph.add_edge(
                Edge(
                    from_id=script_node_id,
                    to_id=owner_id,
                    type="attached_to",
                    data={
                        "scope": scope_id,
                        "inspector_values": _scalarize(comp.inspector_values),
                    },
                )
            )
        else:
            cid = make_component_id(owner_id, comp.file_id, comp.type_name)
            graph.add_node(
                Node(
                    id=cid,
                    type="Component",
                    data={
                        "component_type": comp.type_name,
                        "class_id": comp.class_id,
                        "scope": scope_id,
                        "file_id": comp.file_id,
                        "inspector_values": _scalarize(comp.inspector_values),
                    },
                )
            )
            graph.add_edge(Edge(from_id=cid, to_id=owner_id, type="attached_to"))

    # Emit co_exists_with edges: every pair of components on the same GameObject.
    for go in parsed.gameobjects:
        owner_id = go_id_by_fileid[go.file_id]
        # Gather all neighbor node ids for this GameObject.
        neighbors: list[str] = []
        for comp_fid in go.component_file_ids:
            lookup = parsed.components_by_fileid.get(comp_fid)
            if lookup is None:
                continue
            if lookup.class_id == SCRIPT_CLASS_ID and lookup.script_guid:
                script_id = mb_fileid_to_script_id.get(comp_fid)
                if script_id:
                    neighbors.append(script_id)
            else:
                neighbors.append(make_component_id(owner_id, comp_fid, lookup.type_name))
        for i, a in enumerate(neighbors):
            for b in neighbors[i + 1 :]:
                graph.add_edge(Edge(from_id=a, to_id=b, type="co_exists_with"))

    # Emit subscribes_to edges from event connections.
    for comp in parsed.components:
        if comp.class_id != SCRIPT_CLASS_ID:
            continue
        src_script_id = mb_fileid_to_script_id.get(comp.file_id)
        if src_script_id is None:
            continue
        for ec in comp.event_connections:
            target_script_id = mb_fileid_to_script_id.get(ec.target_file_id)
            if target_script_id is None:
                continue
            graph.add_edge(
                Edge(
                    from_id=src_script_id,
                    to_id=target_script_id,
                    type="subscribes_to",
                    data={
                        "field": ec.field_name,
                        "method": ec.method_name,
                        "mode": ec.argument_mode,
                    },
                )
            )


def _scalarize(values: dict[str, Any]) -> dict[str, Any]:
    """Keep Inspector values JSON-serializable.

    Unity YAML occasionally produces nested dicts for vectors/colors; we keep
    those as-is. Any objects that made it through unparsed (shouldn't happen
    with ``yaml.safe_load``) are stringified.
    """
    clean: dict[str, Any] = {}
    for k, v in values.items():
        clean[k] = _clean_value(v)
    return clean


def _clean_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _collect_references(paths: Iterable[Path]) -> None:  # pragma: no cover — reserved for I3
    """Placeholder — prefab variant refs get ingested here in I3."""
