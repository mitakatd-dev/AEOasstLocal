"""
Tests for automatic stale-worker reconciliation in GET /api/runner/status
and run cleanup in DELETE /api/runner/workers.

When a Cloud Run Job exits without sending /complete (crash, timeout,
DB connection drop), the worker goes stale. These tests verify that:

1. GET /api/runner/status auto-reconciles a stale worker:
   - Worker status transitions running → stopped in DB (idempotent)
   - Its pending WorkerBatch records are marked "error"
   - Its "running" Run records are marked "failed"
   - A second call does NOT re-process (already stopped)

2. DELETE /api/runner/workers (Reset Workers) also fails orphaned runs
   before clearing worker/batch records.

3. _detect_batches tolerates runs with triggered_at=None (no 500).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    make_prompt, make_run,
    make_browser_worker, make_worker_batch,
)


def _inject_admin(app):
    from app.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"uid": "t", "role": "admin"}


def _clear(app):
    from app.auth import get_current_user
    app.dependency_overrides.pop(get_current_user, None)


def _stale_worker(db, session_id):
    """Create a worker + batch whose last_heartbeat is 10 minutes ago."""
    from app.models import BrowserWorker
    w = make_browser_worker(db, name=f"chatgpt-{uuid.uuid4().hex[:4]}", status="running")
    # Backdate the heartbeat so it looks stale
    stale_hb = datetime.now(timezone.utc) - timedelta(minutes=10)
    w.last_heartbeat = stale_hb
    db.commit()
    make_worker_batch(db, worker_id=w.id, session_id=session_id, status="running")
    return w


class TestStaleAutoReconcile:

    def test_stale_worker_runs_marked_failed_on_status_poll(self, test_engine, db):
        """GET /api/runner/status auto-fails runs for stale workers."""
        from app.main import app
        from app.models import Run, BrowserWorker
        session = f"stale-auto-{uuid.uuid4().hex[:6]}"
        p = make_prompt(db, label=f"Stale-{session}")
        make_run(db, p.id, session_id=session, status="running")
        make_run(db, p.id, session_id=session, status="running")
        w = _stale_worker(db, session)

        with TestClient(app) as c:
            r = c.get("/api/runner/status")
            assert r.status_code == 200

        # Runs must now be failed
        runs = db.query(Run).filter(Run.session_id == session).all()
        assert all(r.status == "failed" for r in runs), \
            f"Expected all failed, got: {[r.status for r in runs]}"

    def test_stale_worker_status_updated_to_stopped(self, test_engine, db):
        """Worker DB record transitions running → stopped after one status poll."""
        from app.main import app
        from app.models import BrowserWorker
        session = f"stale-status-{uuid.uuid4().hex[:6]}"
        p = make_prompt(db, label=f"StaleStatus-{session}")
        make_run(db, p.id, session_id=session, status="running")
        w = _stale_worker(db, session)
        worker_id = w.id

        with TestClient(app) as c:
            c.get("/api/runner/status")

        db.expire_all()
        updated = db.query(BrowserWorker).filter(BrowserWorker.id == worker_id).first()
        assert updated.status == "stopped"

    def test_stale_auto_reconcile_is_idempotent(self, test_engine, db):
        """Calling status twice does not double-process the worker."""
        from app.main import app
        from app.models import Run
        session = f"stale-idem-{uuid.uuid4().hex[:6]}"
        p = make_prompt(db, label=f"StaleIdem-{session}")
        make_run(db, p.id, session_id=session, status="running")
        _stale_worker(db, session)

        with TestClient(app) as c:
            c.get("/api/runner/status")  # first poll — reconciles
            c.get("/api/runner/status")  # second poll — no-op

        runs = db.query(Run).filter(Run.session_id == session).all()
        assert all(r.status == "failed" for r in runs)

    def test_stale_does_not_affect_done_workers(self, test_engine, db):
        """Workers already in done/stopped status are not re-processed."""
        from app.main import app
        from app.models import Run, BrowserWorker
        session = f"stale-done-{uuid.uuid4().hex[:6]}"
        p = make_prompt(db, label=f"StaleDone-{session}")
        run = make_run(db, p.id, session_id=session, status="completed")
        run_id = run.id

        # Worker already marked done — should not touch its runs
        w = make_browser_worker(db, name=f"done-{uuid.uuid4().hex[:4]}", status="done")
        stale_hb = datetime.now(timezone.utc) - timedelta(minutes=10)
        w.last_heartbeat = stale_hb
        db.commit()
        make_worker_batch(db, worker_id=w.id, session_id=session, status="completed")

        with TestClient(app) as c:
            c.get("/api/runner/status")

        db.expire_all()
        r = db.query(Run).filter(Run.id == run_id).first()
        assert r.status == "completed"  # untouched

    def test_stale_does_not_affect_other_sessions(self, test_engine, db):
        """Only the stale worker's session runs are failed — not unrelated runs."""
        from app.main import app
        from app.models import Run
        stale_session = f"stale-tgt-{uuid.uuid4().hex[:6]}"
        other_session = f"stale-oth-{uuid.uuid4().hex[:6]}"
        p = make_prompt(db, label=f"StaleIso-{stale_session}")
        make_run(db, p.id, session_id=stale_session, status="running")
        other_run = make_run(db, p.id, session_id=other_session, status="running")
        other_run_id = other_run.id
        _stale_worker(db, stale_session)

        with TestClient(app) as c:
            c.get("/api/runner/status")

        db.expire_all()
        r = db.query(Run).filter(Run.id == other_run_id).first()
        assert r.status == "running"  # untouched


class TestResetWorkersCleanup:

    def test_reset_workers_fails_orphaned_running_runs(self, test_engine, db):
        """DELETE /api/runner/workers marks running runs as failed before wiping workers."""
        from app.main import app
        from app.models import Run
        session = f"reset-runs-{uuid.uuid4().hex[:6]}"
        p = make_prompt(db, label=f"Reset-{session}")
        make_run(db, p.id, session_id=session, status="running")
        make_run(db, p.id, session_id=session, status="running")
        w = make_browser_worker(db, name=f"rw-{uuid.uuid4().hex[:4]}", status="running")
        make_worker_batch(db, worker_id=w.id, session_id=session, status="running")

        _inject_admin(app)
        try:
            with TestClient(app) as c:
                r = c.delete("/api/runner/workers")
                assert r.status_code == 200
        finally:
            _clear(app)

        runs = db.query(Run).filter(Run.session_id == session).all()
        assert all(r.status == "failed" for r in runs)

    def test_reset_workers_does_not_affect_already_completed_runs(self, test_engine, db):
        """Completed runs are not touched by reset."""
        from app.main import app
        from app.models import Run
        session = f"reset-comp-{uuid.uuid4().hex[:6]}"
        p = make_prompt(db, label=f"ResetComp-{session}")
        run = make_run(db, p.id, session_id=session, status="completed")
        run_id = run.id
        w = make_browser_worker(db, name=f"rwc-{uuid.uuid4().hex[:4]}", status="done")
        make_worker_batch(db, worker_id=w.id, session_id=session, status="completed")

        _inject_admin(app)
        try:
            with TestClient(app) as c:
                c.delete("/api/runner/workers")
        finally:
            _clear(app)

        db.expire_all()
        r = db.query(Run).filter(Run.id == run_id).first()
        assert r.status == "completed"


class TestDetectBatchesNoneGuard:

    def test_detect_batches_tolerates_null_triggered_at(self, db):
        """A Run with triggered_at=None must not crash _detect_batches."""
        from app.models import Run
        from app.routers.runs import _detect_batches
        p = make_prompt(db, label="NullTriggered")
        # Insert a run with no triggered_at (bypassing the default)
        run = Run(prompt_id=p.id, status="completed", triggered_at=None)
        db.add(run)
        db.commit()
        # Must not raise
        result = _detect_batches(db)
        assert isinstance(result, list)
