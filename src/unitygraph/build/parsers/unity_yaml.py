"""Unity YAML pre-processing + loading.

Unity's scene/prefab files are YAML 1.1 with a custom tag convention:

    --- !u!<classID> &<fileID>
    TypeName:
      field: value

PyYAML doesn't know how to resolve ``!u!`` tags. The safe fix is to normalize
each document header so PyYAML sees a standard mapping, and preserve the
``classID`` + ``fileID`` as a sibling metadata record.

We also parse Unity's flow-style fileID/guid references
(``{fileID: 123}`` / ``{fileID: 123, guid: abc, type: 3}``) -- those parse
fine as ordinary mappings in YAML 1.1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

# Prefer the C-backed loader when libyaml is available -- typically 5-10x faster
# than the pure-Python one on Unity scene/prefab files. Falls back gracefully.
try:
    _YAML_LOADER: type[yaml.SafeLoader] = yaml.CSafeLoader  # type: ignore[assignment]
except AttributeError:  # pragma: no cover -- libyaml missing
    _YAML_LOADER = yaml.SafeLoader

_DOC_HEADER_RE = re.compile(r"^---\s+!u!(\d+)\s+&(-?\d+)(\s+stripped)?\s*$", re.MULTILINE)

# Class IDs we actually care about. Parsing + materializing dicts for the other
# 90% of scene contents (lighting, navmesh, occlusion culling, etc.) is the
# single biggest perf cost on large real-world projects. Callers that need
# everything (tests, non-scene consumers) can pass ``class_filter=None``.
DEFAULT_CLASS_FILTER: frozenset[int] = frozenset(
    {
        1,  # GameObject
        4,  # Transform
        20,  # Camera
        33,  # MeshFilter
        54,  # Rigidbody
        64,  # MeshCollider
        65,  # BoxCollider
        82,  # AudioSource
        92,  # Behaviour
        95,  # Animator
        102,  # TextMesh
        111,  # Animation
        114,  # MonoBehaviour
        135,  # SphereCollider
        136,  # CapsuleCollider
        137,  # SkinnedMeshRenderer
        143,  # CharacterController
        146,  # CharacterJoint
        154,  # TerrainCollider
        161,  # Terrain
        195,  # NavMeshAgent
        198,  # ParticleSystem
        199,  # ParticleSystemRenderer
        210,  # SortingGroup
        212,  # SpriteRenderer
        224,  # RectTransform
        330,  # LODGroup
        1001,  # PrefabInstance
    }
)


@dataclass
class UnityDoc:
    """One ``---`` document inside a Unity YAML file.

    Attributes
    ----------
    class_id:
        Unity's numeric classID (e.g. ``1`` = GameObject, ``4`` = Transform,
        ``114`` = MonoBehaviour, ``54`` = Rigidbody).
    file_id:
        Local fileID (anchor) -- unique within the file, referenced by
        ``{fileID: N}`` elsewhere.
    type_name:
        The top-level type key in the document body (e.g. ``GameObject``).
    body:
        Whatever sits under ``type_name`` -- typically a mapping of fields.
    stripped:
        True if the document was the ``stripped`` variant (prefab instance
        override markers). We record it but don't special-case yet.
    header_line:
        1-indexed line number of the ``--- !u!...`` separator. v1.5+.
    body_text:
        Raw substring of the document body. Lets line lookups (find_key_line)
        compute file-level line numbers without re-parsing.
    """

    class_id: int
    file_id: int
    type_name: str
    body: dict[str, Any] = field(default_factory=dict)
    stripped: bool = False
    header_line: int = 0
    body_text: str = ""

    def find_key_line(self, key: str, *, indent: int = 2) -> int:
        """Return the file-level 1-indexed line of ``key:`` inside body_text.

        Looks for a line shaped like ``  key:`` at the given indentation
        (Unity's usual two-space top-level body indent). Returns 0 if
        not found, which callers should treat as "unknown".

        Line math: ``body_text`` begins at ``match.end()`` -- which lands at
        the ``\\n`` terminating the header line, so the first element of
        ``splitlines(keepends=True)`` is just that trailing ``\\n`` (a
        phantom empty line). We subtract 1 to compensate, so the document's
        type-name line (``MonoBehaviour:``, etc.) maps to ``header_line + 1``.
        """
        if not self.body_text:
            return 0
        prefix = " " * indent + key + ":"
        for line_in_body, raw in enumerate(self.body_text.splitlines(keepends=True)):
            if raw.startswith(prefix):
                return self.header_line + line_in_body
        return 0


def load_documents(
    text: str,
    *,
    class_filter: frozenset[int] | None = DEFAULT_CLASS_FILTER,
) -> list[UnityDoc]:
    """Parse a Unity YAML file into a list of ``UnityDoc`` records.

    The strategy: split by ``---`` separators using the regex, parse each
    body as plain YAML, and attach the classID/fileID from the header.

    ``class_filter`` is an allowlist of class IDs to materialize -- documents
    with other class IDs are skipped before YAML parsing, which is the
    expensive step. Pass ``None`` to materialize every document.

    Unknown or malformed documents are skipped silently (the builder logs
    them in aggregate -- see ``build/builder.py``).
    """
    headers = list(_DOC_HEADER_RE.finditer(text))
    if not headers:
        return []

    # Cumulative line numbers per byte offset -- built lazily when a doc
    # actually needs its header_line. Pre-computing the full table once
    # is O(n) and amortizes over all documents.
    line_starts: list[int] = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            line_starts.append(i + 1)

    def _line_for_offset(byte_off: int) -> int:
        # Binary search line_starts for the largest start <= byte_off.
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= byte_off:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1  # 1-indexed

    docs: list[UnityDoc] = []
    for i, match in enumerate(headers):
        class_id = int(match.group(1))
        if class_filter is not None and class_id not in class_filter:
            continue
        file_id = int(match.group(2))
        stripped = bool(match.group(3))
        header_line = _line_for_offset(match.start())
        body_start = match.end()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body_raw = text[body_start:body_end]
        body_text = body_raw.strip()
        if not body_text:
            continue
        try:
            payload = yaml.load(body_text, Loader=_YAML_LOADER)
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
                header_line=header_line,
                body_text=body_raw,
            )
        )
    return docs


def is_script_ref(value: Any) -> bool:
    """True if ``value`` looks like ``{fileID: N, guid: ..., type: ...}``."""
    return isinstance(value, dict) and "fileID" in value and "guid" in value


def extract_script_guid(value: Any) -> str | None:
    """Return the guid from a Unity script reference, or None."""
    if is_script_ref(value):
        guid = value.get("guid")
        return str(guid) if guid else None
    return None
