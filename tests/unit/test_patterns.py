"""Tests for the Layer 3 failure pattern map."""

from __future__ import annotations

import time

import pytest

from unitygraph.behavior import extractor, patterns


@pytest.fixture
def store(tmp_path):
    db = tmp_path / "patterns.db"
    with patterns.PatternStore(db) as s:
        yield s


def test_pre_seed_patterns_installed(store):
    all_pats = store.list_all()
    names = {p.pattern_id for p in all_pats}
    assert "seed_implicit_rigidbody" in names
    assert "seed_inspector_override_blindness" in names
    assert "seed_lifecycle_race" in names
    assert "seed_coroutine_destroy" in names
    assert "seed_event_connection_gap" in names
    assert "seed_prefab_override_surprise" in names
    assert len(all_pats) == 6
    assert all(p.status == "observed" for p in all_pats)
    assert all(p.confidence == pytest.approx(0.3) for p in all_pats)


def test_observe_correct_raises_confidence(store):
    pat = store.get("seed_inspector_override_blindness")
    assert pat is not None
    before = pat.confidence

    updated = store.observe("seed_inspector_override_blindness", "correct")
    assert updated is not None
    assert updated.confidence > before
    assert updated.evidence_count == pat.evidence_count + 1


def test_observe_incorrect_lowers_confidence(store):
    updated = store.observe("seed_inspector_override_blindness", "incorrect")
    assert updated is not None
    assert updated.confidence < 0.3
    assert updated.evidence_count == 1


def test_auto_promotion_after_threshold(store):
    pid = "seed_inspector_override_blindness"
    # 5 consecutive correct feedbacks should cross the (ev >= 5, conf >= 0.6) bar.
    for _ in range(5):
        store.observe(pid, "correct")
    pat = store.get(pid)
    assert pat is not None
    assert pat.status == "active"
    assert pat.confidence >= patterns.PROMOTION_MIN_CONFIDENCE
    assert pat.evidence_count >= patterns.PROMOTION_MIN_EVIDENCE


def test_manual_promote(store):
    store.promote("seed_implicit_rigidbody")
    pat = store.get("seed_implicit_rigidbody")
    assert pat is not None
    assert pat.status == "active"


def test_decay_archives_inactive_low_confidence_patterns(store):
    # Age out a single pattern: low confidence + stale last_seen.
    pid = "seed_coroutine_destroy"
    store.observe(pid, "incorrect")
    pat = store.get(pid)
    assert pat is not None
    pat.last_seen_ts = time.time() - (patterns.DECAY_INACTIVE_DAYS + 1) * 86400
    store.upsert(pat)

    archived = store.decay()
    assert pid in archived
    pat_after = store.get(pid)
    assert pat_after is not None
    assert pat_after.status == "archived"


def test_extractor_matches_pattern_triggers(store):
    injection = {
        "task_text": "tune the [SerializeField] Inspector value for _speed",
        "session_id": "s1",
    }
    result = extractor.extract_from_feedback(store, injection, "correct")
    assert "seed_inspector_override_blindness" in result.matched_pattern_ids


def test_extractor_does_not_match_unrelated_task(store):
    injection = {
        "task_text": "rename the Foo class to Bar",
        "session_id": "s1",
    }
    result = extractor.extract_from_feedback(store, injection, "correct")
    # No pattern should fire for a pure-rename task.
    assert "seed_inspector_override_blindness" not in result.matched_pattern_ids


def test_replay_session_log_processes_pairs(store):
    events = [
        {"event_type": "injection", "session_id": "s1", "task_text": "Inspector tuning _speed"},
        {"event_type": "feedback", "session_id": "s1", "verdict": "correct"},
        {"event_type": "injection", "session_id": "s1", "task_text": "something unrelated"},
        {"event_type": "feedback", "session_id": "s1", "verdict": "incorrect"},
    ]
    n = extractor.replay_session_log(store, events)
    assert n == 2


def test_stats_reflects_counts(store):
    stats = store.stats()
    assert stats["total"] == 6
    assert stats["by_status"].get("observed", 0) == 6
    assert stats["mean_confidence"] == pytest.approx(0.3)
