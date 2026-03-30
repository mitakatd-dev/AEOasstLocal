"""
Tests for POST /api/runner/stop — persistence of the stop action.

Verifies that stopping a runner:
  1. Marks the BrowserWorker status to "stopped" in the DB.
  2. Marks any in-progress Runs belonging to the worker's session as "failed".
  3. Does NOT affect runs from other sessions.
  4. Is blocked for viewers (403).

Note: runner_manager.stop() is a no-op in the test environment (no real subprocess),
but the DB-side effects are what we're verifying here.
"""
from __future__ import annotations

import uuid
import pytest

from tests.conftest import (
    make_prompt, make_run,
    make_browser_worker, make_worker_batch,
)


def _inject_role(app, role):
    from app.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"uid": "t", "email": "t@t.com", "role": role}


def _clear(app):
    from app.auth import get_current_user
    app.dependency_overrides.pop(get_current_user, None)


class TestStopPersistence:

    def test_stop_marks_worker_status_stopped(self, test_engine, db):
        from app.main import app
        from app.models import BrowserWorker
        worker_name = f"chatgpt-stop-{uuid.uuid4().hex[:6]}"
        make_browser_worker(db, name=worker_name, platform="chatgpt", status="running")

        _inject_role(app, "admin")
        try:
            from fastapi.testclient import TestClient
            with TestClient(app) as c:
                r = c.post("/api/runner/stop", json={"name": worker_name})
                assert r.status_code == 200
        finally:
            _clear(app)

        # All workers with this name should now be "stopped"
        workers = db.query(BrowserWorker).filter(BrowserWorker.name == worker_name).all()
        assert all(w.status == "stopped" for w in workers)

    def test_stop_marks_running_runs_as_failed(self, test_engine, db):
        from app.main import app
        from app.models import Run, BrowserWorker
        session = f"stop-sess-{uuid.uuid4().hex[:6]}"
        worker_name = f"gemini-stop-{uuid.uuid4().hex[:6]}"
        p = make_prompt(db, label=f"StopRuns-{session}")
        make_run(db, p.id, session_id=session, status="running")
        make_run(db, p.id, session_id=session, status="running")

        worker = make_browser_worker(db, name=worker_name, platform="gemini", status="running")
        make_worker_batch(db, worker_id=worker.id, session_id=session, status="running")

        _inject_role(app, "admin")
        try:
            from fastapi.testclient import TestClient
            with TestClient(app) as c:
                r = c.post("/api/runner/stop", json={"name": worker_name})
                assert r.status_code == 200
        finally:
            _clear(app)

        runs = db.query(Run).filter(Run.session_id == session).all()
        assert all(r.status == "failed" for r in runs), \
            f"Expected all runs failed, got: {[r.status for r in runs]}"

    def test_stop_does_not_affect_other_session_runs(self, test_engine, db):
        from app.main import app
        from app.models import Run
        session_target  = f"stop-target-{uuid.uuid4().hex[:6]}"
        session_other   = f"stop-other-{uuid.uuid4().hex[:6]}"
        worker_name     = f"perp-stop-{uuid.uuid4().hex[:6]}"
        p = make_prompt(db, label=f"StopIsolation-{session_target}")
        make_run(db, p.id, session_id=session_target, status="running")
        make_run(db, p.id, session_id=session_other,  status="running")

        worker = make_browser_worker(db, name=worker_name, platform="perplexity", status="running")
        make_worker_batch(db, worker_id=worker.id, session_id=session_target, status="running")

        _inject_role(app, "admin")
        try:
            from fastapi.testclient import TestClient
            with TestClient(app) as c:
                c.post("/api/runner/stop", json={"name": worker_name})
        finally:
            _clear(app)

        other_runs = db.query(Run).filter(Run.session_id == session_other).all()
        # Runs in the unrelated session must NOT be changed to "failed"
        assert all(r.status == "running" for r in other_runs)

    def test_stop_is_admin_only(self, test_engine):
        from app.main import app
        _inject_role(app, "viewer")
        try:
            from fastapi.testclient import TestClient
            with TestClient(app) as c:
                r = c.post("/api/runner/stop", json={"name": "some-worker"})
                assert r.status_code == 403
        finally:
            _clear(app)

    def test_stop_worker_not_in_db_still_returns_ok(self, test_engine):
        """Stopping a worker name that has no DB record should not raise."""
        from app.main import app
        _inject_role(app, "admin")
        try:
            from fastapi.testclient import TestClient
            with TestClient(app) as c:
                r = c.post("/api/runner/stop", json={"name": "ghost-worker-xyz"})
                assert r.status_code == 200
        finally:
            _clear(app)


class TestHeartbeatGuard:
    """
    These tests cover the regression gap that caused stop to be un-done.

    The stop endpoint correctly marks the worker 'stopped' in DB.
    But the Cloud Run Job keeps running for a few seconds after stop and
    sends one more heartbeat — without a guard, that heartbeat was
    overwriting 'stopped' back to 'running', silently undoing the stop.

    Every test here MUST stay green; a failure means we've re-introduced
    that regression.
    """

    def test_heartbeat_does_not_resurrect_stopped_worker(self, test_engine, db):
        """
        Core regression test: a heartbeat after stop must NOT change status
        back to 'running'.
        """
        from app.main import app
        from app.models import BrowserWorker
        from fastapi.testclient import TestClient

        worker_name = f"chatgpt-hb-guard-{uuid.uuid4().hex[:6]}"
        w = make_browser_worker(db, name=worker_name, status="running")
        worker_id = w.id

        # Simulate the stop endpoint having already run
        w.status = "stopped"
        db.commit()

        with TestClient(app) as c:
            r = c.post("/api/runner/heartbeat", json={
                "worker_id": worker_id,
                "status": "running",
                "completed": 5,
                "batch_id": "test-batch",
            })
            assert r.status_code == 200

        db.expire_all()
        updated = db.query(BrowserWorker).filter(BrowserWorker.id == worker_id).first()
        assert updated.status == "stopped", (
            "Heartbeat must NOT overwrite 'stopped' status — "
            "this is the regression that caused stop to be undone on page refresh"
        )

    def test_heartbeat_returns_stop_signal_for_stopped_worker(self, test_engine, db):
        """
        Heartbeat for a stopped worker must return {ok: False, stop: True}
        so the runner exits gracefully without waiting for the next 30s cycle.
        """
        from app.main import app
        from fastapi.testclient import TestClient

        worker_name = f"chatgpt-hb-sig-{uuid.uuid4().hex[:6]}"
        w = make_browser_worker(db, name=worker_name, status="stopped")

        with TestClient(app) as c:
            r = c.post("/api/runner/heartbeat", json={
                "worker_id": w.id,
                "status": "running",
            })
            assert r.status_code == 200
            body = r.json()
            assert body["ok"] is False
            assert body["stop"] is True

    def test_heartbeat_updates_running_worker_normally(self, test_engine, db):
        """Normal heartbeat for a running worker must still update status and log lines."""
        from app.main import app
        from app.models import BrowserWorker
        from fastapi.testclient import TestClient

        worker_name = f"chatgpt-hb-ok-{uuid.uuid4().hex[:6]}"
        w = make_browser_worker(db, name=worker_name, status="running")

        with TestClient(app) as c:
            r = c.post("/api/runner/heartbeat", json={
                "worker_id": w.id,
                "status": "paused",
                "log_lines": ["line1", "line2"],
            })
            assert r.status_code == 200
            assert r.json()["ok"] is True

        db.expire_all()
        updated = db.query(BrowserWorker).filter(BrowserWorker.id == w.id).first()
        assert updated.status == "paused"
        assert "line1" in (updated.log_lines or "")

    def test_heartbeat_for_done_worker_does_not_resurrect(self, test_engine, db):
        """Workers in 'done' state should also be protected — a late heartbeat
        after the batch completed must not flip them back to 'running'."""
        from app.main import app
        from app.models import BrowserWorker
        from fastapi.testclient import TestClient

        worker_name = f"chatgpt-hb-done-{uuid.uuid4().hex[:6]}"
        w = make_browser_worker(db, name=worker_name, status="done")

        with TestClient(app) as c:
            r = c.post("/api/runner/heartbeat", json={
                "worker_id": w.id,
                "status": "running",
            })
            assert r.status_code == 200

        db.expire_all()
        updated = db.query(BrowserWorker).filter(BrowserWorker.id == w.id).first()
        # 'done' is a terminal state — a rogue heartbeat must not undo it
        assert updated.status == "done"

    def test_register_saves_execution_name(self, test_engine, db):
        """Execution name from Cloud Run must be persisted at register time
        so stop works on any service instance (not just the one that launched)."""
        from app.main import app
        from app.models import BrowserWorker
        from fastapi.testclient import TestClient

        exec_name = f"projects/p/locations/r/jobs/j/executions/{uuid.uuid4().hex[:8]}"

        with TestClient(app) as c:
            r = c.post("/api/runner/register", json={
                "name": f"chatgpt-reg-{uuid.uuid4().hex[:6]}",
                "platform": "chatgpt",
                "execution_name": exec_name,
            })
            assert r.status_code == 200
            worker_id = r.json()["worker_id"]

        db.expire_all()
        w = db.query(BrowserWorker).filter(BrowserWorker.id == worker_id).first()
        assert w.execution_name == exec_name
