"""Parser for ``ProjectSettings/MonoManager.asset`` — script execution order.

MonoManager stores a list of ``m_DefaultExecutionOrder`` entries, each with a
script guid and a numeric order value. Negative values run earlier, positive
values run later, 0 is default.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .unity_yaml import load_documents


@dataclass
class ExecutionOrderEntry:
    guid: str
    order: int


def parse_file(path: Path) -> list[ExecutionOrderEntry]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    docs = load_documents(text)
    entries: list[ExecutionOrderEntry] = []
    for doc in docs:
        if doc.type_name != "MonoManager":
            continue
        raw = doc.body.get("m_DefaultExecutionOrder") or []
        for item in raw:
            if not isinstance(item, dict):
                continue
            guid = item.get("m_GUID")
            order = item.get("m_Value", 0)
            if guid is None:
                continue
            try:
                entries.append(ExecutionOrderEntry(guid=str(guid), order=int(order)))
            except (TypeError, ValueError):
                continue
    return entries
