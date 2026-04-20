"""Unity YAML pre-processing + loading.

Unity's scene/prefab files are YAML 1.1 with a custom tag convention:

    --- !u!<classID> &<fileID>
    TypeName:
      field: value

PyYAML doesn't know how to resolve ``!u!`` tags. The safe fix is to normalize
each document header so PyYAML sees a standard mapping, and preserve the
``classID`` + ``fileID`` as a sibling metadata record.

We also parse Unity's flow-style fileID/guid references
(``{fileID: 123}`` / ``{fileID: 123, guid: abc, type: 3}``) — those parse
fine as ordinary mappings in YAML 1.1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

_DOC_HEADER_RE = re.compile(r"^---\s+!u!(\d+)\s+&(-?\d+)(\s+stripped)?\s*$", re.MULTILINE)


@dataclass
class UnityDoc:
    """One ``---`` document inside a Unity YAML file.

    Attributes
    ----------
    class_id:
        Unity's numeric classID (e.g. ``1`` = GameObject, ``4`` = Transform,
        ``114`` = MonoBehaviour, ``54`` = Rigidbody).
    file_id:
        Local fileID (anchor) — unique within the file, referenced by
        ``{fileID: N}`` elsewhere.
    type_name:
        The top-level type key in the document body (e.g. ``GameObject``).
    body:
        Whatever sits under ``type_name`` — typically a mapping of fields.
    stripped:
        True if the document was the ``stripped`` variant (prefab instance
        override markers). We record it but don't special-case yet.
    """

    class_id: int
    file_id: int
    type_name: str
    body: dict[str, Any] = field(default_factory=dict)
    stripped: bool = False


def load_documents(text: str) -> list[UnityDoc]:
    """Parse a Unity YAML file into a list of ``UnityDoc`` records.

    The strategy: split by ``---`` separators using the regex, parse each
    body as plain YAML, and attach the classID/fileID from the header.

    Unknown or malformed documents are skipped silently (the builder logs
    them in aggregate — see ``build/builder.py``).
    """
    headers = list(_DOC_HEADER_RE.finditer(text))
    if not headers:
        return []

    docs: list[UnityDoc] = []
    for i, match in enumerate(headers):
        class_id = int(match.group(1))
        file_id = int(match.group(2))
        stripped = bool(match.group(3))
        body_start = match.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body_text = text[body_start:body_end].strip()
        if not body_text:
            continue
        try:
            payload = yaml.safe_load(body_text)
        except yaml.YAMLError:
            continue
        if not isinstance(payload, dict) or not payload:
            continue
        type_name, body = next(iter(payload.items()))
        if not isinstance(body, dict):
            body = {}
        docs.append(
            UnityDoc(
                class_id=class_id,
                file_id=file_id,
                type_name=str(type_name),
                body=body,
                stripped=stripped,
            )
        )
    return docs


def is_script_ref(value: Any) -> bool:
    """True if ``value`` looks like ``{fileID: N, guid: ..., type: ...}``."""
    return (
        isinstance(value, dict)
        and "fileID" in value
        and "guid" in value
    )


def extract_script_guid(value: Any) -> str | None:
    """Return the guid from a Unity script reference, or None."""
    if is_script_ref(value):
        guid = value.get("guid")
        return str(guid) if guid else None
    return None
