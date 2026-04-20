"""Render a ``Subgraph`` as the UNITYGRAPH CONTEXT block (spec §2.4).

Format looks like::

    === UNITYGRAPH CONTEXT ===
    TASK-RELEVANT SCENE DATA
    ------------------------
    GameObject: Player
      Components: [PlayerController, Rigidbody, ...]
      PlayerController Inspector values:
        _speed: 5.0  (code default: 5.0)

    COMPONENT RELATIONSHIPS
    -----------------------
    PlayerController.Update() -> Rigidbody.AddForce()  [depends_on]
    ...

    LIFECYCLE NOTES
    ---------------
    HealthSystem runs before PlayerController (Script Execution Order)

    GRAPH CONFIDENCE: HIGH
    TOKEN USAGE: 340 tokens
    =========================

Confidence is HIGH when every included Script has an Inspector value on its
attachment edge, MEDIUM when some are missing, LOW when the retrieval found
no scene attachment at all.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from unitygraph.build.graph import Edge, Node

from .retrieval import Subgraph


@dataclass
class FormattedContext:
    text: str
    confidence: str  # HIGH / MEDIUM / LOW
    token_count: int = 0


def format_subgraph(subgraph: Subgraph, token_count: int = 0) -> FormattedContext:
    lines: list[str] = []
    lines.append("=== UNITYGRAPH CONTEXT ===")

    # Section 1: scene data (GameObjects + their attachments)
    lines.append("TASK-RELEVANT SCENE DATA")
    lines.append("-" * 24)
    scene_block, scripts_with_inspector, scripts_total = _render_scene_section(subgraph)
    lines.extend(scene_block)
    lines.append("")

    # Section 2: component relationships (typed edges between scripts/components)
    rel_block = _render_relationships_section(subgraph)
    if rel_block:
        lines.append("COMPONENT RELATIONSHIPS")
        lines.append("-" * 23)
        lines.extend(rel_block)
        lines.append("")

    # Section 3: prefab chain (is_variant_of / overrides)
    prefab_block = _render_prefab_chain_section(subgraph)
    if prefab_block:
        lines.append("PREFAB CHAIN")
        lines.append("-" * 12)
        lines.extend(prefab_block)
        lines.append("")

    # Section 4: lifecycle notes (execution order, FindObjectOfType calls)
    lifecycle_block = _render_lifecycle_section(subgraph)
    if lifecycle_block:
        lines.append("LIFECYCLE NOTES")
        lines.append("-" * 15)
        lines.extend(lifecycle_block)
        lines.append("")

    confidence = _confidence(scripts_with_inspector, scripts_total, subgraph)
    lines.append(f"GRAPH CONFIDENCE: {confidence} (strategy={subgraph.strategy or 'none'})")
    lines.append(f"TOKEN USAGE: {token_count} tokens")
    lines.append("=" * 25)

    return FormattedContext(text="\n".join(lines), confidence=confidence, token_count=token_count)


def _render_scene_section(subgraph: Subgraph) -> tuple[list[str], int, int]:
    nodes_by_id = {n.id: n for n in subgraph.nodes}
    attachments_by_owner: dict[str, list[tuple[str, Node, dict[str, Any]]]] = defaultdict(list)
    for edge in subgraph.edges:
        if edge.type != "attached_to":
            continue
        comp = nodes_by_id.get(edge.from_id)
        if comp is None:
            continue
        attachments_by_owner[edge.to_id].append((comp.type, comp, edge.data))

    lines: list[str] = []
    scripts_total = 0
    scripts_with_inspector = 0

    gameobjects = [n for n in subgraph.nodes if n.type == "GameObject"]
    if not gameobjects:
        lines.append("(no GameObjects matched — retrieval returned only global nodes)")
        return lines, scripts_with_inspector, scripts_total

    for go in gameobjects:
        attached = attachments_by_owner.get(go.id, [])
        if not attached:
            continue
        script_names = [n.data.get("name", "?") for (t, n, _d) in attached if t == "Script"]
        component_names = [
            n.data.get("component_type", n.data.get("name", "?"))
            for (t, n, _d) in attached
            if t == "Component"
        ]
        all_names = script_names + component_names
        lines.append(f"GameObject: {go.data.get('name', '?')}  (scope={go.data.get('scope', '?')})")
        lines.append(f"  Components: [{', '.join(all_names)}]")

        for type_name, comp_node, edge_data in attached:
            if type_name != "Script":
                continue
            scripts_total += 1
            inspector = edge_data.get("inspector_values") or {}
            defaults = {
                f.get("name"): f.get("default")
                for f in comp_node.data.get("fields") or []
                if isinstance(f, dict)
            }
            if inspector:
                scripts_with_inspector += 1
            if inspector:
                lines.append(f"  {comp_node.data.get('name')} Inspector values:")
                for k, v in inspector.items():
                    default = defaults.get(k)
                    if default is None:
                        lines.append(f"    {k}: {_fmt_value(v)}")
                    else:
                        lines.append(f"    {k}: {_fmt_value(v)}  (code default: {default})")
            elif defaults:
                lines.append(f"  {comp_node.data.get('name')} code defaults only:")
                for k, v in defaults.items():
                    if v is None:
                        continue
                    lines.append(f"    {k}: {v}")

    if not lines:
        lines.append("(no GameObject attachments in the retrieved subgraph)")
    return lines, scripts_with_inspector, scripts_total


def _render_relationships_section(subgraph: Subgraph) -> list[str]:
    nodes_by_id = {n.id: n for n in subgraph.nodes}
    out: list[str] = []
    for edge in subgraph.edges:
        if edge.type not in {"depends_on", "subscribes_to", "inherits", "calls", "transitions_to"}:
            continue
        src = nodes_by_id.get(edge.from_id)
        dst = nodes_by_id.get(edge.to_id)
        if src is None or dst is None:
            continue
        out.append(
            f"{src.data.get('name', src.type)} -> {dst.data.get('name', dst.type)}  [{edge.type}]"
        )
    return out


def _render_prefab_chain_section(subgraph: Subgraph) -> list[str]:
    nodes_by_id = {n.id: n for n in subgraph.nodes}
    out: list[str] = []
    for edge in subgraph.edges:
        if edge.type == "is_variant_of":
            src = nodes_by_id.get(edge.from_id)
            dst = nodes_by_id.get(edge.to_id)
            if src is None or dst is None:
                continue
            out.append(f"{src.data.get('name', '?')} <- variant of <- {dst.data.get('name', '?')}")
        elif edge.type == "overrides":
            src = nodes_by_id.get(edge.from_id)
            if src is None:
                continue
            path = edge.data.get("property_path", "")
            value = edge.data.get("value")
            out.append(f"  override: {src.data.get('name', '?')}.{path} = {value}")
    return out


def _render_lifecycle_section(subgraph: Subgraph) -> list[str]:
    out: list[str] = []
    ordered = [
        (n.data.get("name", "?"), n.data["execution_order"])
        for n in subgraph.nodes
        if n.type == "Script" and "execution_order" in n.data
    ]
    if len(ordered) > 1:
        ordered.sort(key=lambda x: x[1])
        labels = [f"{name}({order})" for name, order in ordered]
        out.append("Execution order: " + " -> ".join(labels))
    find_obj = [
        (n.data.get("name", "?"), list(n.data.get("find_object_of_type_types") or []))
        for n in subgraph.nodes
        if n.type == "Script" and n.data.get("find_object_of_type_types")
    ]
    for name, types in find_obj:
        for t in types:
            out.append(f"{name}.Awake() calls FindObjectOfType<{t}>()")
    return out


_MAX_VALUE_CHARS = 80


def _fmt_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    # Collapse big Inspector blobs — UnityEvent persistent-call trees, vectors
    # with thousands of keyframes, etc. — into a short shape hint so the
    # formatter stays within the token budget on noisy projects.
    if isinstance(value, dict):
        rendered = str(value)
        if len(rendered) > _MAX_VALUE_CHARS:
            keys = ", ".join(list(value)[:3])
            return f"{{...{keys}... ({len(value)} fields)}}"
        return rendered
    if isinstance(value, list):
        rendered = str(value)
        if len(rendered) > _MAX_VALUE_CHARS:
            return f"[... {len(value)} items ...]"
        return rendered
    text = str(value)
    if len(text) > _MAX_VALUE_CHARS:
        return text[: _MAX_VALUE_CHARS - 3] + "..."
    return text


def _confidence(
    scripts_with_inspector: int,
    scripts_total: int,
    subgraph: Subgraph,
) -> str:
    if scripts_total == 0:
        return "LOW" if not subgraph.nodes else "MEDIUM"
    ratio = scripts_with_inspector / scripts_total
    if ratio >= 0.75:
        return "HIGH"
    if ratio >= 0.25:
        return "MEDIUM"
    return "LOW"


def trim_to_budget(subgraph: Subgraph, max_nodes: int) -> Subgraph:
    """Shrink ``subgraph`` down to at most ``max_nodes`` nodes, preserving seeds first."""
    if len(subgraph.nodes) <= max_nodes:
        return subgraph
    seed_ids = set(subgraph.seed_node_ids)
    kept_ids: list[str] = []
    # Seeds first.
    for n in subgraph.nodes:
        if n.id in seed_ids:
            kept_ids.append(n.id)
    # Fill with remaining nodes preferring Script > GameObject > Component.
    priority = {"Script": 5, "GameObject": 4, "Component": 3, "Prefab": 2, "Scene": 1}
    remaining = sorted(
        (n for n in subgraph.nodes if n.id not in seed_ids),
        key=lambda n: -priority.get(n.type, 0),
    )
    for n in remaining:
        if len(kept_ids) >= max_nodes:
            break
        kept_ids.append(n.id)
    keep_set = set(kept_ids)
    return Subgraph(
        nodes=[n for n in subgraph.nodes if n.id in keep_set],
        edges=[e for e in subgraph.edges if e.from_id in keep_set and e.to_id in keep_set],
        strategy=subgraph.strategy + "+trimmed",
        seed_node_ids=subgraph.seed_node_ids,
        entity_result=subgraph.entity_result,
    )


def _edge_from_json(edge_data: object) -> Edge | None:  # pragma: no cover — helper for readability
    return None
