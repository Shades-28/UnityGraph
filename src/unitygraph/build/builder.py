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
from typing import Any

from .cache import ParseCache
from .graph import (
    Edge,
    Graph,
    Node,
    make_animator_id,
    make_animstate_id,
    make_component_id,
    make_gameobject_id,
    make_prefab_id,
    make_scene_id,
    make_script_id,
    make_shadergraph_id,
)
from .parsers import (
    animator_parser,
    cs_parser,
    execorder_parser,
    meta_parser,
    scene_parser,
    shadergraph_parser,
)
from .parsers.scene_parser import SCRIPT_CLASS_ID, ParsedScene


@dataclass
class BuildWarning:
    category: str  # cs_parser | scene_parser | prefab_parser | meta | duplicate_node
    path: str
    message: str


@dataclass
class BuildReport:
    n_cs: int = 0
    n_scenes: int = 0
    n_prefabs: int = 0
    n_controllers: int = 0
    n_shadergraphs: int = 0
    warnings: list[BuildWarning] = field(default_factory=list)

    def warn(self, category: str, path: str, message: str) -> None:
        self.warnings.append(BuildWarning(category=category, path=path, message=message))

    def tallies(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for w in self.warnings:
            tally[w.category] = tally.get(w.category, 0) + 1
        return tally


@dataclass
class BuildResult:
    graph: Graph
    report: BuildReport


def build_project(
    project_root: Path,
    *,
    cache: ParseCache | None = None,
) -> BuildResult:
    """Parse a Unity project and produce a graph.

    ``cache`` (optional): a ``ParseCache`` loaded from a previous build. When
    provided, per-file parse results are reused for files whose (mtime, size)
    haven't changed since the last run. The cache is mutated in place with
    new parse results for changed/new files; call ``cache.write()`` after the
    build to persist it.
    """
    start = time.perf_counter()
    graph = Graph(project_root=str(project_root.resolve()))
    report = BuildReport()

    # 1. Discover asset files.
    cs_files = _discover(project_root, "*.cs", skip_generated=True)
    scene_files = _discover(project_root, "*.unity", skip_generated=True)
    prefab_files = _discover(project_root, "*.prefab", skip_generated=True)
    controller_files = _discover(project_root, "*.controller", skip_generated=True)
    shader_files = _discover(project_root, "*.shadergraph", skip_generated=True)

    report.n_cs = len(cs_files)
    report.n_scenes = len(scene_files)
    report.n_prefabs = len(prefab_files)
    report.n_controllers = len(controller_files)
    report.n_shadergraphs = len(shader_files)

    # 2. guid -> asset path (for script ref resolution).
    guid_index = meta_parser.build_guid_index(project_root)

    # 3. Parse C# scripts. Map guid -> first class in file (Unity convention).
    script_class_by_guid: dict[str, tuple[cs_parser.ClassInfo, Path]] = {}
    parsed_scripts: list[tuple[Path, list[cs_parser.ClassInfo]]] = []
    for path in cs_files:
        rel = str(path.relative_to(project_root))
        cached = cache.get(rel, path) if cache is not None else None
        if isinstance(cached, cs_parser.ParsedScript):
            parsed = cached
        else:
            try:
                parsed = cs_parser.parse_file(path)
            except Exception as exc:
                report.warn("cs_parser", str(path), str(exc))
                continue
            if cache is not None:
                cache.put(rel, path, parsed)
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
            if not graph.try_add_node(node):
                report.warn("duplicate_node", rel, f"Script node id already exists: {node.id}")
                continue
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
        rel_scene = str(scene_path.relative_to(project_root))
        cached_scene = cache.get(rel_scene, scene_path) if cache is not None else None
        if isinstance(cached_scene, ParsedScene):
            scene_parsed = cached_scene
        else:
            try:
                scene_parsed = scene_parser.parse_file(scene_path)
            except Exception as exc:
                report.warn("scene_parser", str(scene_path), str(exc))
                continue
            if cache is not None:
                cache.put(rel_scene, scene_path, scene_parsed)
        rel = str(scene_path.relative_to(project_root))
        scene_id = make_scene_id(scene_path.stem, rel)
        if not graph.try_add_node(
            Node(
                id=scene_id,
                type="Scene",
                data={"name": scene_path.stem, "file_path": rel},
            )
        ):
            report.warn("duplicate_node", rel, f"Scene node id already exists: {scene_id}")
            continue
        _ingest_scene(graph, scene_id, scene_parsed, script_class_by_guid, guid_index, report)

    # Track prefab guid → prefab_id for is_variant_of edges. Also remember each
    # parsed scene/prefab so we can do a second pass for overrides after all
    # prefab nodes exist.
    prefab_id_by_guid: dict[str, str] = {}
    variant_work: list[tuple[str, ParsedScene]] = []
    for prefab_path in prefab_files:
        rel_prefab = str(prefab_path.relative_to(project_root))
        cached_pref = cache.get(rel_prefab, prefab_path) if cache is not None else None
        if isinstance(cached_pref, ParsedScene):
            prefab_parsed = cached_pref
        else:
            try:
                prefab_parsed = scene_parser.parse_file(prefab_path)
            except Exception as exc:
                report.warn("prefab_parser", str(prefab_path), str(exc))
                continue
            if cache is not None:
                cache.put(rel_prefab, prefab_path, prefab_parsed)
        rel_pref = str(prefab_path.relative_to(project_root))
        prefab_id = make_prefab_id(prefab_path.stem, rel_pref)
        if not graph.try_add_node(
            Node(
                id=prefab_id,
                type="Prefab",
                data={"name": prefab_path.stem, "file_path": rel_pref},
            )
        ):
            report.warn("duplicate_node", rel_pref, f"Prefab node id already exists: {prefab_id}")
            continue

        meta = prefab_path.with_suffix(prefab_path.suffix + ".meta")
        pg = meta_parser.load_meta_guid(meta) if meta.exists() else None
        if pg:
            prefab_id_by_guid[pg] = prefab_id

        _ingest_scene(graph, prefab_id, prefab_parsed, script_class_by_guid, guid_index, report)
        variant_work.append((prefab_id, prefab_parsed))

    # 5b. Resolve prefab variant chains.
    _emit_variant_edges(graph, variant_work, prefab_id_by_guid)

    # 6. Animator Controllers → AnimatorController + AnimState nodes, transitions_to + contains_state edges.
    _ingest_animators(graph, controller_files, project_root, report, cache)

    # 7. ShaderGraphs → ShaderGraph nodes, uses_subgraph edges.
    _ingest_shadergraphs(graph, shader_files, project_root, report, cache)

    # 8. Parse execution order → annotate Script nodes.
    exec_order_path = project_root / "ProjectSettings" / "MonoManager.asset"
    exec_entries = execorder_parser.parse_file(exec_order_path)
    order_by_guid = {e.guid: e.order for e in exec_entries}
    # Build a single (guid -> script_node_id) lookup upfront.
    node_id_by_guid: dict[str, str] = {}
    for guid, (klass, path) in script_class_by_guid.items():
        rel = str(path.relative_to(project_root))
        node_id_by_guid[guid] = make_script_id(klass.name, rel)
    nodes_by_id = {n.id: n for n in graph.nodes}
    for guid, order in order_by_guid.items():
        node_id = node_id_by_guid.get(guid)
        if node_id is None:
            continue
        target = nodes_by_id.get(node_id)
        if target is not None:
            target.data["execution_order"] = order

    graph.build_ms = int((time.perf_counter() - start) * 1000)
    return BuildResult(graph=graph, report=report)


def _discover(root: Path, pattern: str, *, skip_generated: bool) -> list[Path]:
    """Walk ``root`` for files matching ``pattern``, honoring the skip list.

    Only the path *relative to* ``root`` is inspected — absolute segments like
    ``C:\\Users\\...\\Temp\\...`` from a temp-dir test harness no longer
    collide with Unity's ``Temp/`` output folder.
    """
    out: list[Path] = []
    skip_dirs = {"Library", "Temp", "obj", "Build", "Builds", "Logs"}
    for path in root.rglob(pattern):
        if skip_generated:
            try:
                rel_parts = set(path.relative_to(root).parts)
            except ValueError:
                rel_parts = set()
            if rel_parts & skip_dirs:
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
    ids = graph.script_ids_by_name(class_name)
    return ids[0] if ids else None


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
        if not graph.try_add_node(
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
        ):
            report.warn("duplicate_node", scope_id, f"GameObject node id already exists: {gid}")
            continue

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
                unknown_name = (
                    Path(ext_rel).stem
                    if ext_rel.endswith(".cs")
                    else f"UnknownScript_{comp.script_guid[:8]}"
                )
                placeholder_id = make_script_id(unknown_name, ext_rel)
                if not graph.has_node(placeholder_id):
                    graph.try_add_node(
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
            if graph.try_add_node(
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
            ):
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


def _emit_variant_edges(
    graph: Graph,
    variant_work: list[tuple[str, ParsedScene]],
    prefab_id_by_guid: dict[str, str],
) -> None:
    """Emit ``is_variant_of`` + ``overrides`` edges from PrefabInstance blocks."""
    for variant_id, parsed in variant_work:
        for instance in parsed.prefab_instances:
            if not instance.source_prefab_guid:
                continue
            parent_id = prefab_id_by_guid.get(instance.source_prefab_guid)
            if parent_id is None:
                continue
            graph.add_edge(
                Edge(
                    from_id=variant_id,
                    to_id=parent_id,
                    type="is_variant_of",
                )
            )
            for override in instance.overrides:
                if not override.property_path:
                    continue
                graph.add_edge(
                    Edge(
                        from_id=variant_id,
                        to_id=parent_id,
                        type="overrides",
                        data={
                            "target_file_id": override.target_file_id,
                            "property_path": override.property_path,
                            "value": override.value,
                        },
                    )
                )


def _ingest_animators(
    graph: Graph,
    controller_files: list[Path],
    project_root: Path,
    report: BuildReport,
    cache: ParseCache | None = None,
) -> None:
    for path in controller_files:
        rel = str(path.relative_to(project_root))
        cached = cache.get(rel, path) if cache is not None else None
        if isinstance(cached, animator_parser.ParsedAnimator):
            parsed = cached
        else:
            try:
                parsed = animator_parser.parse_file(path)
            except Exception as exc:
                report.warn("animator_parser", str(path), str(exc))
                continue
            if cache is not None:
                cache.put(rel, path, parsed)
        anim_id = make_animator_id(parsed.controller_name, rel)
        if not graph.try_add_node(
            Node(
                id=anim_id,
                type="AnimatorController",
                data={
                    "name": parsed.controller_name,
                    "file_path": rel,
                    "parameters": [
                        {"name": p.name, "type": p.type_name, "default": p.default}
                        for p in parsed.parameters
                    ],
                    "layers": [
                        {"name": layer.name, "state_machine_file_id": layer.state_machine_file_id}
                        for layer in parsed.layers
                    ],
                },
            )
        ):
            report.warn("duplicate_node", rel, f"AnimatorController id exists: {anim_id}")
            continue

        state_id_by_fileid: dict[int, str] = {}
        for state in parsed.states:
            state_id = make_animstate_id(anim_id, state.file_id, state.name)
            if not graph.try_add_node(
                Node(
                    id=state_id,
                    type="AnimState",
                    data={
                        "name": state.name,
                        "controller": anim_id,
                        "file_id": state.file_id,
                        "motion_guid": state.motion_guid,
                    },
                )
            ):
                continue
            state_id_by_fileid[state.file_id] = state_id
            graph.add_edge(Edge(from_id=anim_id, to_id=state_id, type="contains_state"))

        for transition in parsed.transitions:
            src = state_id_by_fileid.get(transition.source_state_file_id)
            dst = (
                state_id_by_fileid.get(transition.dest_state_file_id)
                if transition.dest_state_file_id is not None
                else None
            )
            if src is None or dst is None:
                continue
            graph.add_edge(
                Edge(
                    from_id=src,
                    to_id=dst,
                    type="transitions_to",
                    data={
                        "conditions": transition.conditions,
                        "has_exit_time": transition.has_exit_time,
                        "duration": transition.duration,
                    },
                )
            )


def _ingest_shadergraphs(
    graph: Graph,
    shader_files: list[Path],
    project_root: Path,
    report: BuildReport,
    cache: ParseCache | None = None,
) -> None:
    shader_id_by_guid: dict[str, str] = {}
    parsed_shaders: list[tuple[str, shadergraph_parser.ParsedShaderGraph]] = []

    for path in shader_files:
        rel = str(path.relative_to(project_root))
        cached = cache.get(rel, path) if cache is not None else None
        if isinstance(cached, shadergraph_parser.ParsedShaderGraph):
            parsed = cached
        else:
            try:
                parsed = shadergraph_parser.parse_file(path)
            except Exception as exc:
                report.warn("shadergraph_parser", str(path), str(exc))
                continue
            if cache is not None:
                cache.put(rel, path, parsed)
        shader_id = make_shadergraph_id(parsed.name, rel)
        if not graph.try_add_node(
            Node(
                id=shader_id,
                type="ShaderGraph",
                data={
                    "name": parsed.name,
                    "file_path": rel,
                    "properties": [
                        {"name": p.name, "type": p.type_name, "reference": p.reference}
                        for p in parsed.properties
                    ],
                    "keywords": [
                        {"name": k.name, "type": k.type_name, "reference": k.reference}
                        for k in parsed.keywords
                    ],
                    "output_slots": list(parsed.output_slots),
                },
            )
        ):
            report.warn("duplicate_node", rel, f"ShaderGraph id exists: {shader_id}")
            continue
        parsed_shaders.append((shader_id, parsed))

        # Index by meta guid so uses_subgraph edges can resolve.
        meta = path.with_suffix(path.suffix + ".meta")
        guid = meta_parser.load_meta_guid(meta) if meta.exists() else None
        if guid:
            shader_id_by_guid[guid] = shader_id

    # Emit uses_subgraph edges in a second pass (so all shader nodes exist).
    for shader_id, parsed in parsed_shaders:
        for subgraph_guid in parsed.subgraph_refs:
            target_id = shader_id_by_guid.get(subgraph_guid)
            if target_id is None or target_id == shader_id:
                continue
            graph.add_edge(Edge(from_id=shader_id, to_id=target_id, type="uses_subgraph"))
