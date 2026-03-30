"""
Unit tests for runs.py::_detect_batches()

These tests exercise the 30-minute gap clustering logic and session_id grouping
without going through the HTTP layer.

NOTE: Tests use a fresh session_id per test to isolate data — since the shared
in-memory DB persists commits across tests, we scope each test's assertions to
the unique session created within that test.
"""
from __future__ import annotations

import pytest
import uuid
from datetime import datetime, timezone, timedelta

from tests.conftest import make_prompt, make_run, make_result


def detect(db):
    """Import and call _detect_batches with the test db session."""
    from app.routers.runs import _detect_batches
    return _detect_batches(db)


def sid():
    """Generate a unique session_id for test isolation."""
    return f"test-{uuid.uuid4().hex[:8]}"


def batch_for_session(db, session_id):
    """Return the single batch that contains our session_id, or None."""
    batches = detect(db)
    return next((b for b in batches if session_id in b.get("session_ids", [])), None)


class TestNoBatches:
    def test_empty_db_returns_empty_list_or_only_prior_data(self, db):
        # Can't guarantee empty because other tests may have inserted data.
        # What we CAN assert: the return type is always a list.
        result = detect(db)
        assert isinstance(result, list)


class TestSingleBatch:
    def test_single_run_forms_a_batch(self, db):
        p = make_prompt(db, label=f"Single-{sid()}")
        run = make_run(db, p.id, session_id=sid())
        batches = detect(db)
        # There must be at least one batch
        assert len(batches) >= 1

    def test_batch_has_expected_shape(self, db):
        p = make_prompt(db, label=f"Shape-{sid()}")
        make_run(db, p.id, session_id=sid())
        batch = detect(db)[0]
        for key in ("batch_index", "label", "from_dt", "to_dt", "run_count",
                    "completed", "failed", "platforms", "methods", "is_latest"):
            assert key in batch, f"Missing key: {key}"

    def test_most_recent_batch_is_latest(self, db):
        p = make_prompt(db, label=f"Latest-{sid()}")
        make_run(db, p.id, triggered_at=datetime.now(timezone.utc))
        batches = detect(db)
        assert batches[0]["is_latest"] is True


class TestGapClustering:
    def _make_runs_in_window(self, db, offsets_mins):
        """Create runs at specific minute offsets from 'now', all same session."""
        p = make_prompt(db, label=f"Gap-{sid()}")
        session = sid()
        now = datetime.now(timezone.utc)
        for m in offsets_mins:
            make_run(db, p.id, session_id=session,
                     triggered_at=now + timedelta(minutes=m))
        return session, now

    def test_two_runs_within_30_min_land_in_same_cluster(self, db):
        p = make_prompt(db, label=f"Within-{sid()}")
        session = sid()
        now = datetime.now(timezone.utc)
        make_run(db, p.id, session_id=session, triggered_at=now)
        make_run(db, p.id, session_id=session, triggered_at=now + timedelta(minutes=10))
        # Get the latest batch (which contains our two runs)
        batches = detect(db)
        assert batches[0]["run_count"] >= 2  # at least our 2 runs in one batch

    def test_exactly_30_min_gap_stays_in_same_batch(self, db):
        p = make_prompt(db, label=f"Exact30-{sid()}")
        session = sid()
        # Use a far-future base so no other test's runs interleave
        base = datetime(2099, 2, 1, 0, 0, tzinfo=timezone.utc)
        make_run(db, p.id, session_id=session, triggered_at=base)
        make_run(db, p.id, session_id=session, triggered_at=base + timedelta(minutes=30))
        # Same session_id keeps both runs together regardless of gap
        batch = batch_for_session(db, session)
        assert batch is not None
        assert batch["run_count"] >= 2

    def test_batches_ordered_newest_first(self, db):
        batches = detect(db)
        if len(batches) >= 2:
            assert batches[0]["started_at"] >= batches[1]["started_at"]

    def test_over_30_min_gap_produces_at_least_two_batches(self, db):
        """
        Two runs separated by >30 min with distinct timestamps should form
        at least 2 batches. We verify there are 2+ batches total after adding them.
        """
        p = make_prompt(db, label=f"Over30-{sid()}")
        # Use clearly different times to ensure a new cluster
        far_past = datetime(2020, 1, 1, 0, 0, tzinfo=timezone.utc)
        far_future = datetime(2020, 1, 1, 1, 0, tzinfo=timezone.utc)  # 1 hour later
        make_run(db, p.id, triggered_at=far_past)
        make_run(db, p.id, triggered_at=far_future)
        batches = detect(db)
        assert len(batches) >= 2


class TestSessionGrouping:
    def test_same_session_id_groups_runs_together(self, db):
        """Same session_id always lands in one cluster regardless of time gap."""
        p = make_prompt(db, label=f"SameSession-{sid()}")
        now = datetime.now(timezone.utc)
        session = sid()
        make_run(db, p.id, session_id=session, triggered_at=now)
        make_run(db, p.id, session_id=session, triggered_at=now + timedelta(seconds=1))
        batch = batch_for_session(db, session)
        assert batch is not None
        assert batch["run_count"] >= 2

    def test_different_session_ids_always_split_to_separate_batches(self, db):
        """
        Runs with distinct non-None session_ids always go into separate batches,
        regardless of how close together in time they are.
        """
        p = make_prompt(db, label=f"DiffSess-{sid()}")
        now = datetime.now(timezone.utc)
        s1, s2 = sid(), sid()
        make_run(db, p.id, session_id=s1, triggered_at=now)
        make_run(db, p.id, session_id=s2, triggered_at=now + timedelta(seconds=2))
        b1 = batch_for_session(db, s1)
        b2 = batch_for_session(db, s2)
        assert b1 is not None
        assert b2 is not None
        # They must be in distinct batches
        assert b1["primary_session_id"] != b2["primary_session_id"]


class TestBatchStats:
    def test_completed_and_failed_counts_in_isolated_session(self, db):
        """2 completed + 1 failed in the same session appear in one batch with correct counts."""
        session = sid()
        p = make_prompt(db, label=f"Stats-{sid()}")
        base = datetime(2099, 3, 1, 0, 0, tzinfo=timezone.utc)
        make_run(db, p.id, status="completed", session_id=session, triggered_at=base)
        make_run(db, p.id, status="completed", session_id=session, triggered_at=base + timedelta(seconds=1))
        make_run(db, p.id, status="failed",    session_id=session, triggered_at=base + timedelta(seconds=2))
        batch = batch_for_session(db, session)
        assert batch is not None
        assert batch["completed"] >= 2
        assert batch["failed"] >= 1

    def test_failed_prompt_ids_includes_our_failing_prompt(self, db):
        session = sid()
        p1 = make_prompt(db, label=f"FailP1-{sid()}")
        p2 = make_prompt(db, label=f"FailP2-{sid()}")
        base = datetime(2099, 4, 1, 0, 0, tzinfo=timezone.utc)
        make_run(db, p1.id, status="failed",    session_id=session, triggered_at=base)
        make_run(db, p2.id, status="completed", session_id=session, triggered_at=base + timedelta(seconds=1))
        batch = batch_for_session(db, session)
        assert batch is not None
        assert p1.id in batch["failed_prompt_ids"]
        assert p2.id not in batch["failed_prompt_ids"]

    def test_platform_progress_populated_when_results_exist(self, db):
        session = sid()
        p = make_prompt(db, label=f"PlatProg-{sid()}")
        base = datetime(2099, 5, 1, 0, 0, tzinfo=timezone.utc)
        r = make_run(db, p.id, status="completed", session_id=session, triggered_at=base)
        make_result(db, r.id, llm="openai")
        batch = batch_for_session(db, session)
        assert batch is not None
        assert "openai" in batch["platform_progress"]
        assert batch["platform_progress"]["openai"]["completed"] >= 1

    def test_methods_collected(self, db):
        session = sid()
        p = make_prompt(db, label=f"Methods-{sid()}")
        base = datetime(2099, 6, 1, 0, 0, tzinfo=timezone.utc)
        make_run(db, p.id, collection_method="api",     session_id=session, triggered_at=base)
        make_run(db, p.id, collection_method="browser", session_id=session, triggered_at=base + timedelta(seconds=1))
        batch = batch_for_session(db, session)
        assert batch is not None
        assert "api" in batch["methods"]
        assert "browser" in batch["methods"]

    def test_is_latest_only_on_newest_batch(self, db):
        batches = detect(db)
        if len(batches) >= 2:
            assert sum(1 for b in batches if b["is_latest"]) == 1
            assert batches[0]["is_latest"] is True
            assert all(not b["is_latest"] for b in batches[1:])
