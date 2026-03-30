"""
Integration tests for /api/costs/* endpoints.

Verifies:
  - All three endpoints return 200 with correct shape
  - Date window filtering (days param) excludes old records
  - Empty DB returns zero-valued responses (no crashes)
  - per_llm breakdown groups correctly
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest
from tests.conftest import make_prompt, make_run, make_result


class TestCostSummaryEndpoint:
    def test_returns_200(self, client):
        r = client.get("/api/costs/summary")
        assert r.status_code == 200

    def test_response_shape(self, client):
        data = client.get("/api/costs/summary").json()
        assert "total_usd" in data
        assert "breakdown" in data
        assert "per_llm" in data
        assert "window_days" in data
        assert "proxy_source" in data
        bd = data["breakdown"]
        assert "api_tokens_usd" in bd
        assert "proxy_usd" in bd
        assert "infra_usd" in bd

    def test_empty_db_returns_zeros(self, client):
        data = client.get("/api/costs/summary?days=1").json()
        assert data["breakdown"]["api_tokens_usd"] == 0.0

    def test_days_param_accepted(self, client):
        r = client.get("/api/costs/summary?days=7")
        assert r.status_code == 200
        assert r.json()["window_days"] == 7

    def test_api_cost_sums_results_in_window(self, client, db):
        p = make_prompt(db)
        run = make_run(db, p.id, triggered_at=datetime.now(timezone.utc))
        from app.models import Result
        res = Result(
            run_id=run.id,
            llm="openai",
            raw_response="test",
            mentioned=True,
            position_score=0.5,
            sentiment="positive",
            competitors_mentioned="[]",
            latency_ms=100,
            cost_usd=0.05,
        )
        db.add(res)
        db.commit()

        data = client.get("/api/costs/summary?days=30").json()
        assert data["breakdown"]["api_tokens_usd"] >= 0.05

    def test_old_results_excluded_by_window(self, client, db):
        p = make_prompt(db, label="old-prompt-costs")
        old_time = datetime.now(timezone.utc) - timedelta(days=60)
        run = make_run(db, p.id, triggered_at=old_time)
        from app.models import Result
        res = Result(
            run_id=run.id,
            llm="openai",
            raw_response="old",
            mentioned=True,
            position_score=0.5,
            sentiment="positive",
            competitors_mentioned="[]",
            latency_ms=100,
            cost_usd=99.99,
        )
        db.add(res)
        db.commit()

        # 7-day window should not include a 60-day-old result
        data = client.get("/api/costs/summary?days=7").json()
        # total should NOT include 99.99
        assert data["breakdown"]["api_tokens_usd"] < 90.0

    def test_per_llm_groups_by_engine(self, client, db):
        p = make_prompt(db, label="llm-group-test")
        run = make_run(db, p.id)
        from app.models import Result
        for llm, cost in [("openai", 0.10), ("gemini", 0.02)]:
            db.add(Result(
                run_id=run.id,
                llm=llm,
                raw_response="x",
                mentioned=True,
                position_score=0.5,
                sentiment="positive",
                competitors_mentioned="[]",
                latency_ms=100,
                cost_usd=cost,
            ))
        db.commit()

        data = client.get("/api/costs/summary?days=30").json()
        llms = {row["llm"]: row for row in data["per_llm"]}
        assert "openai" in llms
        assert "gemini" in llms
        assert llms["openai"]["cost_usd"] >= 0.10
        assert llms["gemini"]["cost_usd"] >= 0.02

    def test_proxy_source_is_estimate_without_key(self, client, monkeypatch):
        monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
        data = client.get("/api/costs/summary").json()
        assert data["proxy_source"] == "estimate"


class TestCostSessionsEndpoint:
    def test_returns_200(self, client):
        r = client.get("/api/costs/sessions")
        assert r.status_code == 200

    def test_response_has_sessions_key(self, client):
        data = client.get("/api/costs/sessions").json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    def test_days_param_filters_old_sessions(self, client, db):
        p = make_prompt(db, label="sessions-old")
        old_time = datetime.now(timezone.utc) - timedelta(days=120)
        run = make_run(db, p.id, session_id="old-session-abc", triggered_at=old_time)
        result = make_result(db, run.id)

        data = client.get("/api/costs/sessions?days=7").json()
        session_ids = [s["session_id"] for s in data["sessions"]]
        assert "old-session-abc" not in session_ids

    def test_recent_session_appears(self, client, db):
        p = make_prompt(db, label="sessions-recent")
        run = make_run(
            db, p.id,
            session_id="recent-session-xyz",
            triggered_at=datetime.now(timezone.utc),
        )
        make_result(db, run.id)

        data = client.get("/api/costs/sessions?days=30").json()
        session_ids = [s["session_id"] for s in data["sessions"]]
        assert "recent-session-xyz" in session_ids

    def test_session_row_shape(self, client, db):
        p = make_prompt(db, label="sessions-shape")
        run = make_run(
            db, p.id,
            session_id="shape-test-session",
            triggered_at=datetime.now(timezone.utc),
        )
        make_result(db, run.id)

        data = client.get("/api/costs/sessions?days=30").json()
        rows = [s for s in data["sessions"] if s["session_id"] == "shape-test-session"]
        assert rows, "expected session not found in response"
        row = rows[0]
        assert "api_cost_usd" in row
        assert "proxy_cost_usd" in row
        assert "total_usd" in row
        assert "result_count" in row
        assert "collection_method" in row


class TestCostDailyEndpoint:
    def test_returns_200(self, client):
        r = client.get("/api/costs/daily")
        assert r.status_code == 200

    def test_response_has_daily_key(self, client):
        data = client.get("/api/costs/daily").json()
        assert "daily" in data
        assert isinstance(data["daily"], list)

    def test_daily_row_shape(self, client, db):
        p = make_prompt(db, label="daily-shape")
        run = make_run(db, p.id, triggered_at=datetime.now(timezone.utc))
        make_result(db, run.id)

        data = client.get("/api/costs/daily?days=7").json()
        if data["daily"]:
            row = data["daily"][0]
            assert "date" in row
            assert "api_cost_usd" in row
            assert "result_count" in row
            assert "infra_usd" in row

    def test_days_param_excludes_old_data(self, client, db):
        p = make_prompt(db, label="daily-old")
        old_time = datetime.now(timezone.utc) - timedelta(days=60)
        run = make_run(db, p.id, triggered_at=old_time)
        make_result(db, run.id)

        # 7-day window should not contain a 60-day-old record
        data = client.get("/api/costs/daily?days=7").json()
        dates = [row["date"] for row in data["daily"]]
        old_date = old_time.date().isoformat()
        assert old_date not in dates
