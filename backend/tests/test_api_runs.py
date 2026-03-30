"""
Integration tests for /api/runs/ endpoints.

Tests the HTTP layer for run triggering, listing, batch detection,
and session management via the FastAPI TestClient.
"""
from __future__ import annotations

import pytest
from tests.conftest import make_prompt, make_run, make_result, make_citation


class TestHealthCheck:
    def test_health_endpoint_returns_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestTriggerRuns:
    def test_trigger_run_creates_run_records(self, client, db):
        p = make_prompt(db, label="API trigger test")
        r = client.post("/api/runs/", json={
            "prompt_ids": [p.id],
            "platforms": ["openai"],
            "collection_method": "api",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["count"] == 1
        assert len(data["run_ids"]) == 1
        assert "session_id" in data

    def test_trigger_run_auto_generates_session_id(self, client, db):
        p = make_prompt(db, label="Session gen test")
        r = client.post("/api/runs/", json={"prompt_ids": [p.id]})
        assert r.json()["session_id"] is not None

    def test_trigger_run_uses_provided_session_id(self, client, db):
        p = make_prompt(db, label="Session pass test")
        r = client.post("/api/runs/", json={
            "prompt_ids": [p.id],
            "session_id": "my-custom-session-99",
        })
        assert r.json()["session_id"] == "my-custom-session-99"

    def test_trigger_invalid_platform_returns_400(self, client, db):
        p = make_prompt(db, label="Invalid platform test")
        r = client.post("/api/runs/", json={
            "prompt_ids": [p.id],
            "platforms": ["non_existent_llm"],
        })
        assert r.status_code == 400

    def test_trigger_unknown_prompt_id_skipped(self, client, db):
        r = client.post("/api/runs/", json={"prompt_ids": [999999]})
        assert r.status_code == 201
        assert r.json()["count"] == 0

    def test_trigger_multiple_prompts(self, client, db):
        p1 = make_prompt(db, label="Multi 1")
        p2 = make_prompt(db, label="Multi 2")
        r = client.post("/api/runs/", json={"prompt_ids": [p1.id, p2.id]})
        assert r.json()["count"] == 2
        assert len(r.json()["run_ids"]) == 2


class TestListRuns:
    def test_list_runs_returns_list(self, client, db):
        p = make_prompt(db, label="List run test")
        make_run(db, p.id)
        r = client.get("/api/runs/")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_run_by_id(self, client, db):
        p = make_prompt(db, label="Get by ID test")
        run = make_run(db, p.id)
        r = client.get(f"/api/runs/{run.id}")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == run.id
        assert data["prompt_id"] == p.id

    def test_get_nonexistent_run_returns_404(self, client):
        r = client.get("/api/runs/999999")
        assert r.status_code == 404

    def test_run_includes_prompt_label(self, client, db):
        p = make_prompt(db, label="My labelled prompt")
        run = make_run(db, p.id)
        r = client.get(f"/api/runs/{run.id}")
        assert r.json()["prompt_label"] == "My labelled prompt"

    def test_run_includes_results(self, client, db):
        p = make_prompt(db, label="Results included test")
        run = make_run(db, p.id)
        make_result(db, run.id, llm="openai")
        r = client.get(f"/api/runs/{run.id}")
        results = r.json()["results"]
        assert len(results) == 1
        assert results[0]["llm"] == "openai"


class TestBatchesEndpoint:
    def test_batches_returns_list(self, client, db):
        r = client.get("/api/runs/batches")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_batch_contains_expected_fields(self, client, db):
        p = make_prompt(db, label="Batch field test")
        make_run(db, p.id)
        r = client.get("/api/runs/batches")
        batch = r.json()[0]
        for key in ("batch_index", "run_count", "completed", "failed",
                    "platforms", "methods", "is_latest"):
            assert key in batch


class TestSessionsEndpoint:
    def test_sessions_returns_list(self, client, db):
        r = client.get("/api/runs/sessions")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_session_groups_runs_by_session_id(self, client, db):
        p = make_prompt(db, label="Session grouping test")
        make_run(db, p.id, session_id="group-sess-1")
        make_run(db, p.id, session_id="group-sess-1")
        make_run(db, p.id, session_id="group-sess-2")

        sessions = client.get("/api/runs/sessions").json()
        sess1 = next((s for s in sessions if s["session_id"] == "group-sess-1"), None)
        sess2 = next((s for s in sessions if s["session_id"] == "group-sess-2"), None)
        assert sess1 is not None
        assert sess1["prompt_count"] == 2
        assert sess2 is not None
        assert sess2["prompt_count"] == 1

    def test_session_results_endpoint(self, client, db):
        p = make_prompt(db, label="Session results test")
        run = make_run(db, p.id, session_id="res-session-42")
        make_result(db, run.id, llm="gemini")

        r = client.get("/api/runs/sessions/res-session-42/results")
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1
        result_llms = [res["llm"] for item in data for res in item["results"]]
        assert "gemini" in result_llms

    def test_session_results_404_for_unknown_session(self, client):
        r = client.get("/api/runs/sessions/nonexistent-session-xyz/results")
        assert r.status_code == 404


class TestCSVExport:
    def test_export_csv_returns_csv_content(self, client, db):
        p = make_prompt(db, label="CSV export test")
        run = make_run(db, p.id, session_id="csv-sess")
        make_result(db, run.id, llm="perplexity")

        r = client.get("/api/runs/sessions/csv-sess/export")
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        # CSV must contain header row
        content = r.text
        assert "session_id" in content
        assert "llm" in content

    def test_export_csv_contains_result_data(self, client, db):
        p = make_prompt(db, label="CSV data check")
        run = make_run(db, p.id, session_id="csv-data-sess")
        make_result(db, run.id, llm="openai", mentioned=True)

        r = client.get("/api/runs/sessions/csv-data-sess/export")
        assert "openai" in r.text


class TestDeleteSession:
    """
    Tests for DELETE /api/runs/sessions/{session_id}.
    Admin only — deletes Runs + Results + Citations for a session.
    """

    def _inject_admin(self, app):
        from app.auth import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"uid": "u", "email": "a@a.com", "role": "admin"}

    def _inject_viewer(self, app):
        from app.auth import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"uid": "u", "email": "v@v.com", "role": "viewer"}

    def _clear(self, app):
        from app.auth import get_current_user
        app.dependency_overrides.pop(get_current_user, None)

    def test_delete_session_removes_runs(self, test_engine, db):
        from app.main import app
        from app.models import Run
        p = make_prompt(db, label="Del-Runs")
        make_run(db, p.id, session_id="del-sess-runs-1")
        make_run(db, p.id, session_id="del-sess-runs-1")
        self._inject_admin(app)
        try:
            with __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app) as c:
                r = c.delete("/api/runs/sessions/del-sess-runs-1")
                assert r.status_code == 200
                assert r.json()["deleted_runs"] == 2
        finally:
            self._clear(app)
        # Confirm runs are gone from DB
        remaining = db.query(Run).filter(Run.session_id == "del-sess-runs-1").all()
        assert remaining == []

    def test_delete_session_cascades_to_results_and_citations(self, test_engine, db):
        from app.main import app
        from app.models import Run, Result, Citation
        p = make_prompt(db, label="Del-Cascade")
        run = make_run(db, p.id, session_id="del-sess-cascade-1")
        run_id = run.id  # capture before the session expires the instance
        res = make_result(db, run.id, llm="openai")
        res_id = res.id
        make_citation(db, res.id, url="https://example.com/a")
        self._inject_admin(app)
        try:
            with __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app) as c:
                r = c.delete("/api/runs/sessions/del-sess-cascade-1")
                assert r.status_code == 200
        finally:
            self._clear(app)
        # All related records must be gone
        assert db.query(Run).filter(Run.session_id == "del-sess-cascade-1").count() == 0
        assert db.query(Result).filter(Result.run_id == run_id).count() == 0
        assert db.query(Citation).filter(Citation.result_id == res_id).count() == 0

    def test_delete_nonexistent_session_returns_404(self, test_engine):
        from app.main import app
        self._inject_admin(app)
        try:
            with __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app) as c:
                r = c.delete("/api/runs/sessions/no-such-session-xyz-999")
                assert r.status_code == 404
        finally:
            self._clear(app)

    def test_viewer_cannot_delete_session(self, test_engine, db):
        from app.main import app
        p = make_prompt(db, label="Del-Viewer-Block")
        make_run(db, p.id, session_id="del-sess-viewer-block-1")
        self._inject_viewer(app)
        try:
            with __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app) as c:
                r = c.delete("/api/runs/sessions/del-sess-viewer-block-1")
                assert r.status_code == 403
        finally:
            self._clear(app)

    def test_delete_does_not_affect_other_sessions(self, test_engine, db):
        from app.main import app
        from app.models import Run
        p = make_prompt(db, label="Del-Isolation")
        make_run(db, p.id, session_id="del-sess-target-1")
        make_run(db, p.id, session_id="del-sess-other-1")
        self._inject_admin(app)
        try:
            with __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app) as c:
                c.delete("/api/runs/sessions/del-sess-target-1")
        finally:
            self._clear(app)
        # The other session's run must be untouched
        assert db.query(Run).filter(Run.session_id == "del-sess-other-1").count() == 1
