"""Observation-log event schemas.

The observation log is an append-only JSONL stream under
``.unitygraph/sessions/<session_id>.jsonl``. Each line is one event.

Events come in three kinds:

- ``injection`` — ``inject_context`` was called. We record the task, the
  injected block, strategy + confidence, graph identity, seed nodes.
- ``feedback`` — the developer said the output was correct/incorrect, or
  the git watcher inferred acceptance from a commit.
- ``correction`` — the developer changed Claude's output. We record the
  delta so Layer 3 can extract missing-context patterns from it.

All events share a common header: ``event_type``, ``event_id``,
``session_id``, ``timestamp``, ``graph_hash``. The header plus a
``payload`` dict is the on-disk shape.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

EventType = Literal["injection", "feedback", "correction"]


def _new_event_id() -> str:
    return "evt_" + secrets.token_hex(8)


def _utc_iso_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class InjectionEvent:
    session_id: str
    task_text: str
    strategy: str
    confidence: str
    token_count: int
    node_count: int
    edge_count: int
    seed_node_ids: list[str]
    graph_hash: str
    block: str  # the full UNITYGRAPH CONTEXT block
    event_id: str = field(default_factory=_new_event_id)
    timestamp: str = field(default_factory=_utc_iso_now)

    event_type: EventType = "injection"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FeedbackEvent:
    session_id: str
    verdict: Literal["correct", "incorrect", "accepted_via_commit", "reverted"]
    note: str = ""
    event_id: str = field(default_factory=_new_event_id)
    timestamp: str = field(default_factory=_utc_iso_now)
    graph_hash: str = ""
    event_type: EventType = "feedback"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CorrectionEvent:
    session_id: str
    original_output: str
    corrected_output: str
    diff_summary: str
    event_id: str = field(default_factory=_new_event_id)
    timestamp: str = field(default_factory=_utc_iso_now)
    graph_hash: str = ""
    event_type: EventType = "correction"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# JSONL sink
# ---------------------------------------------------------------------------


def sessions_dir(project_root: Path) -> Path:
    return project_root / ".unitygraph" / "sessions"


def _session_path(project_root: Path, session_id: str) -> Path:
    return sessions_dir(project_root) / f"{session_id}.jsonl"


def append_event(
    project_root: Path,
    session_id: str,
    event: InjectionEvent | FeedbackEvent | CorrectionEvent,
) -> Path:
    """Append one event to the session's JSONL log. Returns the file path."""
    path = _session_path(project_root, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
    return path


def iter_session_events(project_root: Path, session_id: str) -> list[dict[str, Any]]:
    path = _session_path(project_root, session_id)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def iter_all_events(project_root: Path) -> list[dict[str, Any]]:
    """Union of all JSONL files under ``sessions_dir``, in filename order."""
    out: list[dict[str, Any]] = []
    sdir = sessions_dir(project_root)
    if not sdir.exists():
        return out
    for path in sorted(sdir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------
# Session ID helpers — derived from env var or timestamp + random suffix.
# ---------------------------------------------------------------------------


def current_session_id() -> str:
    """Return a stable session id for this process.

    Uses ``UNITYGRAPH_SESSION_ID`` when set (lets Claude Code drive
    multi-call sessions through the same log file). Falls back to a
    timestamp + random 4-byte suffix.
    """
    forced = os.environ.get("UNITYGRAPH_SESSION_ID")
    if forced:
        return forced
    return f"s{int(time.time())}_{secrets.token_hex(2)}"


__all__ = [
    "CorrectionEvent",
    "EventType",
    "FeedbackEvent",
    "InjectionEvent",
    "append_event",
    "current_session_id",
    "iter_all_events",
    "iter_session_events",
    "sessions_dir",
]
