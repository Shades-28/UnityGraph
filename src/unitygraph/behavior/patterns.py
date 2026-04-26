"""Layer 3 failure pattern map -- SQLite-backed, append-only, decay-aware.

Schema matches spec §3.4. Stored at
``<project_root>/.unitygraph/patterns.db`` alongside the session logs.

Concepts:

- **Pattern**: a (trigger, missing_context_type, injection_rule) tuple
  with a running ``confidence`` and ``evidence_count``. Starts in the
  ``observed`` state and promotes to ``active`` once thresholds are met.
- **Trigger**: a regex or keyword feature extracted from task text that
  activates the pattern.
- **Missing context type**: one of the fixed categories from the spec
  (``parent_component``, ``inspector_value``, ``event_connection``,
  ``lifecycle_order``, ``prefab_override``, ``coroutine_destroy``).
- **Injection rule**: a string description Layer 2 consumes to modify
  retrieval (e.g. "expand by +1 hop along co_exists_with edges").

The pre-seed loader inserts the 6 known blind spots from spec §3.5 on
first use with low confidence; observation either confirms or refutes
them.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

PatternStatus = Literal["observed", "active", "archived"]
MissingContextType = Literal[
    "parent_component",
    "co_component",
    "inspector_value",
    "event_connection",
    "lifecycle_order",
    "prefab_override",
    "coroutine_destroy",
    "other",
]
TaskType = Literal["bug_fix", "new_feature", "refactor", "explain", "test"]


PROMOTION_MIN_EVIDENCE = 5
PROMOTION_MIN_CONFIDENCE = 0.6
DECAY_INACTIVE_DAYS = 30
DECAY_MIN_CONFIDENCE = 0.5


@dataclass
class Pattern:
    pattern_id: str
    task_type: str
    trigger: str
    missing_context_type: str
    injection_rule: str
    confidence: float = 0.3
    evidence_count: int = 0
    last_seen_ts: float = 0.0
    status: str = "observed"
    project_scope: str = "general"
    source: str = "pre_seed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "task_type": self.task_type,
            "trigger": self.trigger,
            "missing_context_type": self.missing_context_type,
            "injection_rule": self.injection_rule,
            "confidence": self.confidence,
            "evidence_count": self.evidence_count,
            "last_seen_ts": self.last_seen_ts,
            "status": self.status,
            "project_scope": self.project_scope,
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# Pre-seed patterns from spec §3.5. Low confidence to start; observation
# promotes or retires.
# ---------------------------------------------------------------------------

PRE_SEED_PATTERNS: list[Pattern] = [
    Pattern(
        pattern_id="seed_implicit_rigidbody",
        task_type="bug_fix",
        trigger=r"\b(AddForce|velocity|rigidbody|physics)\b",
        missing_context_type="co_component",
        injection_rule="expand co_exists_with edges +1 hop for physics scripts",
        confidence=0.3,
        source="pre_seed",
    ),
    Pattern(
        pattern_id="seed_inspector_override_blindness",
        task_type="bug_fix",
        trigger=r"\[SerializeField\]|Inspector|tuning|value",
        missing_context_type="inspector_value",
        injection_rule="always inject Inspector values for [SerializeField] fields on mentioned scripts",
        confidence=0.3,
        source="pre_seed",
    ),
    Pattern(
        pattern_id="seed_lifecycle_race",
        task_type="bug_fix",
        trigger=r"\b(initializ|null ?reference|execution ?order|Awake|Start)\b",
        missing_context_type="lifecycle_order",
        injection_rule="inject script execution order when multiple scripts interact",
        confidence=0.3,
        source="pre_seed",
    ),
    Pattern(
        pattern_id="seed_coroutine_destroy",
        task_type="bug_fix",
        trigger=r"\b(StartCoroutine|IEnumerator|WaitFor)\b.*\b(destroy|disable|inactive)\b",
        missing_context_type="coroutine_destroy",
        injection_rule="inject GameObject active-state + destruction patterns for coroutine scripts",
        confidence=0.3,
        source="pre_seed",
    ),
    Pattern(
        pattern_id="seed_event_connection_gap",
        task_type="new_feature",
        trigger=r"\b(UnityEvent|onClick|Button|UI)\b",
        missing_context_type="event_connection",
        injection_rule="always inject get_event_connections for any object with event fields",
        confidence=0.3,
        source="pre_seed",
    ),
    Pattern(
        pattern_id="seed_prefab_override_surprise",
        task_type="explain",
        trigger=r"\b(prefab|variant|override)\b",
        missing_context_type="prefab_override",
        injection_rule="inject prefab override data for any task touching a prefab-sourced object",
        confidence=0.3,
        source="pre_seed",
    ),
]


# ---------------------------------------------------------------------------
# SQLite store
# ---------------------------------------------------------------------------


@dataclass
class PatternStore:
    db_path: Path
    _conn: sqlite3.Connection | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()
        self._seed_if_empty()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> PatternStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------- schema -------------------

    def _ensure_schema(self) -> None:
        assert self._conn is not None
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS patterns (
                pattern_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                trigger TEXT NOT NULL,
                missing_context_type TEXT NOT NULL,
                injection_rule TEXT NOT NULL,
                confidence REAL NOT NULL,
                evidence_count INTEGER NOT NULL,
                last_seen_ts REAL NOT NULL,
                status TEXT NOT NULL,
                project_scope TEXT NOT NULL,
                source TEXT NOT NULL,
                extra_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS ix_patterns_status ON patterns (status);
            CREATE INDEX IF NOT EXISTS ix_patterns_task_type ON patterns (task_type);
            """
        )
        self._conn.commit()

    def _seed_if_empty(self) -> None:
        assert self._conn is not None
        count = self._conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
        if count == 0:
            for p in PRE_SEED_PATTERNS:
                self._insert(p)
            self._conn.commit()

    # ------------------- CRUD -------------------

    def _insert(self, p: Pattern) -> None:
        assert self._conn is not None
        self._conn.execute(
            "INSERT OR REPLACE INTO patterns "
            "(pattern_id, task_type, trigger, missing_context_type, injection_rule, "
            "confidence, evidence_count, last_seen_ts, status, project_scope, source, extra_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                p.pattern_id,
                p.task_type,
                p.trigger,
                p.missing_context_type,
                p.injection_rule,
                p.confidence,
                p.evidence_count,
                p.last_seen_ts,
                p.status,
                p.project_scope,
                p.source,
                "{}",
            ),
        )

    def upsert(self, p: Pattern) -> None:
        assert self._conn is not None
        self._insert(p)
        self._conn.commit()

    def get(self, pattern_id: str) -> Pattern | None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT * FROM patterns WHERE pattern_id = ?", (pattern_id,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_pattern(row)

    def list_all(self, status: str | None = None) -> list[Pattern]:
        assert self._conn is not None
        if status is not None:
            rows = self._conn.execute(
                "SELECT * FROM patterns WHERE status = ? ORDER BY evidence_count DESC",
                (status,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM patterns ORDER BY evidence_count DESC"
            ).fetchall()
        return [_row_to_pattern(r) for r in rows]

    # ------------------- behavior -------------------

    def observe(
        self,
        pattern_id: str,
        verdict: Literal["correct", "incorrect"],
    ) -> Pattern | None:
        """Update a pattern's confidence after a feedback event.

        - ``correct`` after the pattern fired -> +evidence, +confidence
        - ``incorrect`` after it fired -> +evidence, -confidence
        """
        pat = self.get(pattern_id)
        if pat is None:
            return None

        pat.evidence_count += 1
        pat.last_seen_ts = time.time()
        if verdict == "correct":
            pat.confidence = min(1.0, 0.7 * pat.confidence + 0.3 * 1.0)
        else:
            pat.confidence = max(0.0, 0.7 * pat.confidence + 0.3 * 0.0)

        # Automatic promotion.
        if (
            pat.status == "observed"
            and pat.evidence_count >= PROMOTION_MIN_EVIDENCE
            and pat.confidence >= PROMOTION_MIN_CONFIDENCE
        ):
            pat.status = "active"

        self.upsert(pat)
        return pat

    def promote(self, pattern_id: str) -> Pattern | None:
        pat = self.get(pattern_id)
        if pat is None:
            return None
        pat.status = "active"
        self.upsert(pat)
        return pat

    def decay(self, now_ts: float | None = None) -> list[str]:
        """Archive patterns that haven't been seen in DECAY_INACTIVE_DAYS and
        have low confidence. Returns the pattern ids that were archived.
        """
        assert self._conn is not None
        cutoff = (now_ts or time.time()) - DECAY_INACTIVE_DAYS * 86400
        rows = self._conn.execute(
            "SELECT pattern_id FROM patterns "
            "WHERE status != 'archived' "
            "AND last_seen_ts > 0 "
            "AND last_seen_ts < ? "
            "AND confidence < ?",
            (cutoff, DECAY_MIN_CONFIDENCE),
        ).fetchall()
        ids = [r["pattern_id"] for r in rows]
        for pid in ids:
            self._conn.execute(
                "UPDATE patterns SET status = 'archived' WHERE pattern_id = ?",
                (pid,),
            )
        self._conn.commit()
        return ids

    def stats(self) -> dict[str, Any]:
        assert self._conn is not None
        total = self._conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
        by_status = dict(
            self._conn.execute("SELECT status, COUNT(*) FROM patterns GROUP BY status").fetchall()
        )
        by_type = dict(
            self._conn.execute(
                "SELECT missing_context_type, COUNT(*) FROM patterns GROUP BY missing_context_type"
            ).fetchall()
        )
        avg_conf = self._conn.execute("SELECT AVG(confidence) FROM patterns").fetchone()[0] or 0.0
        return {
            "total": total,
            "by_status": by_status,
            "by_missing_context_type": by_type,
            "mean_confidence": round(float(avg_conf), 3),
        }


def _row_to_pattern(row: sqlite3.Row) -> Pattern:
    return Pattern(
        pattern_id=row["pattern_id"],
        task_type=row["task_type"],
        trigger=row["trigger"],
        missing_context_type=row["missing_context_type"],
        injection_rule=row["injection_rule"],
        confidence=float(row["confidence"]),
        evidence_count=int(row["evidence_count"]),
        last_seen_ts=float(row["last_seen_ts"]),
        status=row["status"],
        project_scope=row["project_scope"],
        source=row["source"],
    )


# ---------------------------------------------------------------------------
# Convenience entry point
# ---------------------------------------------------------------------------


def default_store_path(project_root: Path) -> Path:
    return project_root / ".unitygraph" / "patterns.db"


def open_store(project_root: Path) -> PatternStore:
    return PatternStore(db_path=default_store_path(project_root))


__all__ = [
    "DECAY_INACTIVE_DAYS",
    "DECAY_MIN_CONFIDENCE",
    "PRE_SEED_PATTERNS",
    "PROMOTION_MIN_CONFIDENCE",
    "PROMOTION_MIN_EVIDENCE",
    "Pattern",
    "PatternStore",
    "default_store_path",
    "open_store",
]
