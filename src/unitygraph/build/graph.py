"""Graph model + JSON (de)serialization.

Schema (graph.json v1.2) — additive since v1.0.

Node types: Script, GameObject, Component, Scene, Prefab, AnimState,
            AnimatorController, ShaderGraph, Rationale.
Edge types: attached_to, co_exists_with, calls, subscribes_to, depends_on,
            inherits, instantiates, is_variant_of, overrides, transitions_to,
            loads_scene, contains_state, has_animator, uses_subgraph, explains.

v1.2 introduced the evidence layer: every edge carries ``sites: list[Site]``,
each Site recording the (file, line, col, snippet, kind, confidence) that
justifies the edge's existence. Sites come from location-aware parsers
that preserve tree-sitter ``start_point`` / YAML line numbers.

Backwards compatibility: v1.x graphs loaded by this module synthesize
empty ``sites: []`` per edge. Observatory + MCP tools check
``sites_available`` to know whether to render evidence UI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

SCHEMA_VERSION = "1.2"

NodeType = Literal[
    "Script",
    "GameObject",
    "Component",
    "Scene",
    "Prefab",
    "AnimState",
    "AnimatorController",
    "ShaderGraph",
    "Rationale",
]
EdgeType = Literal[
    "attached_to",
    "co_exists_with",
    "calls",
    "subscribes_to",
    "depends_on",
    "inherits",
    "instantiates",
    "is_variant_of",
    "overrides",
    "transitions_to",
    "loads_scene",
    "contains_state",
    "has_animator",
    "uses_subgraph",
    "explains",
]

# The ``kind`` of evidence a Site represents. Keep this tightly enumerated —
# downstream queries pattern-match on these.
SiteKind = Literal[
    "get_component",
    "find_object",
    "method_call",
    "field_decl",
    "inherits",
    "implements",
    "instantiates",
    "subscribes_to",
    "inspector_override",
    "prefab_override",
    "transitions_to",
    "require_component",
]

# Confidence of the evidence. v2.0 only emits EXTRACTED; INFERRED and
# AMBIGUOUS are reserved for pattern-based queries that might ship later.
Confidence = Literal["EXTRACTED", "INFERRED", "AMBIGUOUS"]


@dataclass
class Site:
    """One source-level justification for an edge.

    Follows the Roslyn ``ReferenceLocation`` shape — one logical edge can
    carry many sites, each pointing at a distinct file+line where the
    relationship is observable.
    """

    file: str  # project-relative path
    line: int  # 1-indexed
    col: int  # 1-indexed
    kind: SiteKind
    confidence: Confidence = "EXTRACTED"
    end_line: int | None = None
    end_col: int | None = None
    snippet: str = ""  # the exact source fragment
    containing_method: str | None = None
    reason: str | None = None  # optional human-readable note

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "file": self.file,
            "line": self.line,
            "col": self.col,
            "kind": self.kind,
            "confidence": self.confidence,
        }
        if self.end_line is not None:
            out["end_line"] = self.end_line
        if self.end_col is not None:
            out["end_col"] = self.end_col
        if self.snippet:
            out["snippet"] = self.snippet
        if self.containing_method:
            out["containing_method"] = self.containing_method
        if self.reason:
            out["reason"] = self.reason
        return out

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Site:
        return cls(
            file=str(payload["file"]),
            line=int(payload["line"]),
            col=int(payload.get("col", 1)),
            kind=payload.get("kind", "method_call"),
            confidence=payload.get("confidence", "EXTRACTED"),
            end_line=int(payload["end_line"]) if "end_line" in payload else None,
            end_col=int(payload["end_col"]) if "end_col" in payload else None,
            snippet=str(payload.get("snippet", "")),
            containing_method=payload.get("containing_method"),
            reason=payload.get("reason"),
        )


@dataclass
class Node:
    id: str
    type: NodeType
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            **{k: v for k, v in self.data.items() if k not in {"id", "type"}},
        }


@dataclass
class Edge:
    from_id: str
    to_id: str
    type: EdgeType
    data: dict[str, Any] = field(default_factory=dict)
    sites: list[Site] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        reserved = {"from", "to", "type", "sites"}
        payload: dict[str, Any] = {
            "from": self.from_id,
            "to": self.to_id,
            "type": self.type,
            **{k: v for k, v in self.data.items() if k not in reserved},
        }
        if self.sites:
            payload["sites"] = [s.to_json() for s in self.sites]
        return payload

    def add_site(self, site: Site) -> None:
        """Append a site if it's not already present (dedup on file+line+col)."""
        key = (site.file, site.line, site.col, site.kind)
        if any((s.file, s.line, s.col, s.kind) == key for s in self.sites):
            return
        self.sites.append(site)


@dataclass
class Graph:
    project_root: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    build_ms: int = 0

    _node_ids: set[str] = field(default_factory=set, init=False, repr=False)
    _script_ids_by_name: dict[str, list[str]] = field(default_factory=dict, init=False, repr=False)

    def add_node(self, node: Node) -> None:
        if node.id in self._node_ids:
            raise ValueError(f"duplicate node id: {node.id}")
        self.nodes.append(node)
        self._node_ids.add(node.id)
        if node.type == "Script":
            name = str(node.data.get("name", ""))
            if name:
                self._script_ids_by_name.setdefault(name, []).append(node.id)

    def try_add_node(self, node: Node) -> bool:
        """Add a node if its id is unique; return False on collision.

        Used during project-wide builds where real Unity projects occasionally
        produce duplicate names (asset packs, multi-class .cs files). Callers
        that need strict behavior should use ``add_node``.
        """
        if node.id in self._node_ids:
            return False
        self.add_node(node)
        return True

    def add_edge(self, edge: Edge) -> None:
        # Edges can repeat across builds; we dedupe on (from, to, type).
        self.edges.append(edge)

    def has_node(self, node_id: str) -> bool:
        return node_id in self._node_ids

    def script_ids_by_name(self, name: str) -> list[str]:
        """Return all Script node ids with the given class name. O(1) lookup."""
        return list(self._script_ids_by_name.get(name, ()))

    def nodes_by_id(self) -> dict[str, Node]:
        """Return a dict view for O(1) node id → Node lookup."""
        return {n.id: n for n in self.nodes}

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "project_root": self.project_root,
            "stats": {
                "n_nodes": len(self.nodes),
                "n_edges": len(self.edges),
                "build_ms": self.build_ms,
            },
            "nodes": [n.to_json() for n in self.nodes],
            "edges": [e.to_json() for e in self.edges],
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Graph:
        payload = json.loads(path.read_text(encoding="utf-8"))
        g = cls(
            project_root=payload["project_root"],
            schema_version=payload.get("schema_version", SCHEMA_VERSION),
            generated_at=payload.get("generated_at", ""),
            build_ms=int(payload.get("stats", {}).get("build_ms", 0)),
        )
        for raw in payload.get("nodes", []):
            node_type = raw.pop("type")
            node_id = raw.pop("id")
            g.add_node(Node(id=node_id, type=node_type, data=raw))
        for raw in payload.get("edges", []):
            edge_type = raw.pop("type")
            from_id = raw.pop("from")
            to_id = raw.pop("to")
            raw_sites = raw.pop("sites", [])
            sites = [Site.from_json(s) for s in raw_sites if isinstance(s, dict)]
            g.add_edge(
                Edge(
                    from_id=from_id,
                    to_id=to_id,
                    type=edge_type,
                    data=raw,
                    sites=sites,
                )
            )
        return g

    def sites_available(self) -> bool:
        """True if any edge carries at least one Site (v2+ builds)."""
        return any(e.sites for e in self.edges)


def make_script_id(class_name: str, file_path: str) -> str:
    return f"script::{class_name}::{file_path}"


def make_scene_id(scene_name: str, rel_path: str | None = None) -> str:
    # Unity project can have multiple scenes with the same stem (asset store packs);
    # disambiguate with relative path when provided.
    if rel_path:
        return f"scene::{scene_name}::{rel_path}"
    return f"scene::{scene_name}"


def make_prefab_id(prefab_name: str, rel_path: str | None = None) -> str:
    if rel_path:
        return f"prefab::{prefab_name}::{rel_path}"
    return f"prefab::{prefab_name}"


def make_gameobject_id(scope_id: str, file_id: int, name: str) -> str:
    return f"go::{scope_id}::{file_id}::{name}"


def make_component_id(owner_go_id: str, file_id: int, component_type: str) -> str:
    return f"comp::{owner_go_id}::{file_id}::{component_type}"


def make_animator_id(controller_name: str, rel_path: str) -> str:
    return f"anim::{controller_name}::{rel_path}"


def make_animstate_id(controller_id: str, state_file_id: int, state_name: str) -> str:
    return f"animstate::{controller_id}::{state_file_id}::{state_name}"


def make_shadergraph_id(name: str, rel_path: str) -> str:
    return f"shader::{name}::{rel_path}"
