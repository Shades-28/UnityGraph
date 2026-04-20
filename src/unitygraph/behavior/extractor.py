"""Delta extractor — turns feedback events into pattern observations.

Given a feedback event (``correct`` or ``incorrect``) and the injection
event it's about, figure out which patterns in the store this evidence
supports or refutes, and call ``store.observe(pattern_id, verdict)`` for
each one that fired.

Approach (MVP):
  1. For each pattern in the store, check whether its trigger regex
     matches the injection's ``task_text``.
  2. If yes and ``verdict == 'correct'``, the pattern gets positive
     evidence. If ``verdict == 'incorrect'``, it gets negative evidence.

Refinement (future): also look at the ``block`` field — did the injection
already inject the ``missing_context_type`` the pattern calls out? If it
did and Claude still got it wrong, the pattern is less load-bearing; if it
didn't and Claude got it wrong, the pattern is load-bearing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .patterns import PatternStore


@dataclass
class ExtractionResult:
    matched_pattern_ids: list[str]
    task_text: str
    verdict: str


def extract_from_feedback(
    store: PatternStore,
    injection_event: dict[str, Any],
    feedback_verdict: str,
) -> ExtractionResult:
    """Update every matching pattern given one feedback event + its injection."""
    task_text = str(injection_event.get("task_text", ""))
    matched: list[str] = []
    for pat in store.list_all():
        if pat.status == "archived":
            continue
        try:
            if re.search(pat.trigger, task_text, re.IGNORECASE):
                store.observe(pat.pattern_id, feedback_verdict)  # type: ignore[arg-type]
                matched.append(pat.pattern_id)
        except re.error:
            continue
    return ExtractionResult(
        matched_pattern_ids=matched, task_text=task_text, verdict=feedback_verdict
    )


def replay_session_log(
    store: PatternStore,
    events: list[dict[str, Any]],
) -> int:
    """Walk an event log and feed each (injection, next-feedback) pair through
    the extractor. Returns the number of feedback events processed.
    """
    last_injection_by_session: dict[str, dict[str, Any]] = {}
    processed = 0
    for event in events:
        etype = event.get("event_type")
        sid = event.get("session_id")
        if not sid:
            continue
        if etype == "injection":
            last_injection_by_session[sid] = event
        elif etype == "feedback":
            injection = last_injection_by_session.get(sid)
            if injection is None:
                continue
            verdict = event.get("verdict")
            if verdict in {"correct", "incorrect", "accepted_via_commit", "reverted"}:
                # Collapse implicit signals to explicit correct/incorrect.
                normalized = (
                    "correct" if verdict in {"correct", "accepted_via_commit"} else "incorrect"
                )
                extract_from_feedback(store, injection, normalized)
                processed += 1
    return processed


__all__ = ["ExtractionResult", "extract_from_feedback", "replay_session_log"]
