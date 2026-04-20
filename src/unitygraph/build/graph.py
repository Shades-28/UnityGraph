"""Graph model + JSON (de)serialization.

Schema (graph.json v1.0) — frozen at I1. Additive changes only in later iterations.

Node types: Script, GameObject, Component, Scene, Prefab.
Edge types: attached_to, co_exists_with, calls, subscribes_to, depends_on,
            inherits, instantiates, is_variant_of, overrides, transitions_to,
            loads_scene.

Only the top-level shape, plus required fields (``id``, ``type``, ``from``, ``to``)
are frozen per ``UnityGraph_Development_Plan.md`` §2.1. Per-type payload keys
live under ``data`` on each node/edge, so new fields are always additive.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

SCHEMA_VERSION = "1.1"

NodeType = Literal[
    "Script",
    "GameObject",
    "Component",
    "Scene",
    "Prefab",
    "AnimState",
    "AnimatorController",
    "ShaderGraph",
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
]


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

    def to_json(self) -> dict[str, Any]:
        reserved = {"from", "to", "type"}
        return {
            "from": self.from_id,
            "to": self.to_id,
            "type": self.type,
            **{k: v for k, v in self.data.items() if k not in reserved},
        }


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
            g.add_edge(Edge(from_id=from_id, to_id=to_id, type=edge_type, data=raw))
        return g


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
