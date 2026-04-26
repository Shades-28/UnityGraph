"""ShaderGraph parser.

Unity's ShaderGraph files (``.shadergraph``) are a **stream of concatenated
JSON objects**, not a single document. Each object has ``m_Type``,
``m_ObjectId``, and type-specific fields.

We walk the stream with ``json.JSONDecoder.raw_decode`` and collect only
what the graph cares about per spec §1.3:

- **ShaderProperty** objects (types containing ``ShaderProperty``) →
  expose as graph "properties" (the shader's input surface).
- **KeywordDescriptor** objects → keyword definitions.
- **SubGraphNode** objects → subgraph guid references.
- **MaterialSlot** objects tagged output-facing → "output ports".

Full node connectivity is out of scope for I3 -- we only need the schema
surface that a task prompt might reference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ShaderProperty:
    name: str
    type_name: str
    reference: str | None = None


@dataclass
class ShaderKeyword:
    name: str
    type_name: str
    reference: str | None = None


@dataclass
class ParsedShaderGraph:
    path: Path
    name: str
    properties: list[ShaderProperty] = field(default_factory=list)
    keywords: list[ShaderKeyword] = field(default_factory=list)
    subgraph_refs: list[str] = field(default_factory=list)  # guids
    output_slots: list[str] = field(default_factory=list)  # display names


def parse_file(path: Path) -> ParsedShaderGraph:
    text = path.read_text(encoding="utf-8", errors="replace")
    if text.startswith("\ufeff"):
        text = text[1:]

    result = ParsedShaderGraph(path=path, name=path.stem)
    decoder = json.JSONDecoder()
    idx = 0
    n = len(text)

    while idx < n:
        while idx < n and text[idx].isspace():
            idx += 1
        if idx >= n:
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            break
        idx = end
        if isinstance(obj, dict):
            _ingest(result, obj)

    return result


def _ingest(result: ParsedShaderGraph, obj: dict[str, Any]) -> None:
    type_name = str(obj.get("m_Type", ""))
    if not type_name:
        return

    short = type_name.rsplit(".", 1)[-1]

    if "ShaderProperty" in short:
        result.properties.append(
            ShaderProperty(
                name=str(obj.get("m_Name", "")) or "",
                type_name=short,
                reference=_opt_str(obj.get("m_DefaultReferenceName")),
            )
        )
        return

    if "KeywordDescriptor" in short or short == "ShaderKeyword":
        result.keywords.append(
            ShaderKeyword(
                name=str(obj.get("m_Name", "")) or "",
                type_name=short,
                reference=_opt_str(obj.get("m_ReferenceName"))
                or _opt_str(obj.get("m_DefaultReferenceName")),
            )
        )
        return

    if "SubGraphNode" in short:
        for ref_key in ("m_SubGraphAsset", "m_SubGraphGuid"):
            ref = obj.get(ref_key)
            if isinstance(ref, dict) and ref.get("m_Guid"):
                result.subgraph_refs.append(str(ref["m_Guid"]))
            elif isinstance(ref, str) and ref:
                result.subgraph_refs.append(ref)
        return

    # Output-facing slots on BlockNode / master stack become the "output ports"
    # of the shader -- what it writes into the render pipeline.
    if "BlockNode" in short:
        name = obj.get("m_DisplayName") or obj.get("m_Name")
        if isinstance(name, str) and name:
            result.output_slots.append(name)


def _opt_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
