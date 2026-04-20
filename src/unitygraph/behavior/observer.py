"""Observation-layer integration with ``inject_context``.

The MCP server and CLI both route through ``unitygraph.inject.engine``.
Rather than monkey-patching, the engine calls ``record_injection`` before
returning — this module owns the "where does the log go" decision so the
engine stays ignorant of filesystem concerns.

Enable by setting ``UNITYGRAPH_OBSERVE=1`` (or any truthy value). The log
is always rooted at ``<graph.project_root>/.unitygraph/sessions/``.
Disable by unsetting the env var or passing ``record=False`` on the
engine call path.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

from .schema import (
    CorrectionEvent,
    FeedbackEvent,
    InjectionEvent,
    append_event,
    current_session_id,
)

if TYPE_CHECKING:
    from unitygraph.inject.engine import InjectionResult


def observe_enabled() -> bool:
    """True when ``UNITYGRAPH_OBSERVE`` is truthy."""
    return bool(os.environ.get("UNITYGRAPH_OBSERVE"))


def _graph_hash(project_root: str) -> str:
    return hashlib.sha256(project_root.encode("utf-8")).hexdigest()[:16]


def record_injection(
    project_root: str,
    task_text: str,
    result: InjectionResult,
) -> None:
    """Log one injection if observation is enabled. Never raises."""
    if not observe_enabled():
        return
    try:
        event = InjectionEvent(
            session_id=current_session_id(),
            task_text=task_text,
            strategy=result.strategy,
            confidence=result.confidence,
            token_count=result.token_count,
            node_count=result.node_count,
            edge_count=result.edge_count,
            seed_node_ids=list(result.seed_node_ids),
            graph_hash=_graph_hash(project_root),
            block=result.block,
        )
        append_event(Path(project_root), event.session_id, event)
    except OSError:
        # Observation must never break the caller.
        return


def record_feedback(
    project_root: str,
    session_id: str,
    verdict: str,
    note: str = "",
) -> None:
    event = FeedbackEvent(
        session_id=session_id,
        verdict=verdict,  # type: ignore[arg-type]
        note=note,
        graph_hash=_graph_hash(project_root),
    )
    append_event(Path(project_root), session_id, event)


def record_correction(
    project_root: str,
    session_id: str,
    original_output: str,
    corrected_output: str,
    diff_summary: str,
) -> None:
    event = CorrectionEvent(
        session_id=session_id,
        original_output=original_output,
        corrected_output=corrected_output,
        diff_summary=diff_summary,
        graph_hash=_graph_hash(project_root),
    )
    append_event(Path(project_root), session_id, event)
