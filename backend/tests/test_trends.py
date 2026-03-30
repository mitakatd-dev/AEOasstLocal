"""
Tests for /api/trends/* endpoints.

Covers:
- GET /api/trends/dashboard      — mention rate per day
- GET /api/trends/prompt/{id}    — per-LLM series for one prompt
- GET /api/trends/per-llm        — per-LLM time series
- GET /api/trends/sentiment      — sentiment distribution over time
- GET /api/trends/share-of-voice — brand vs competitors

All tests use the shared in-memory SQLite engine from conftest.
"""
from __future__ import annotations

import os
import pytest

from tests.conftest import make_prompt, make_run, make_result


class TestDashboardTrend:

    def test_returns_list_shape(self, client, db):
        p = make_prompt(db)
        r = make_run(db, p.id)
        make_result(db, r.id, mentioned=True)

        resp = client.get("/api/trends/dashboard")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert isinstance(body["data"], list)

    def test_mention_rate_calculated(self, client, db):
        from datetime import datetime, timezone, timedelta
        # Use triggered_at 1 minute ago so the ceiling ("now" truncated to seconds)
        # is definitely after the stored value (microseconds excluded).
        past = datetime.now(timezone.utc) - timedelta(minutes=1)
        p = make_prompt(db, label="DashTrend-calc")
        r = make_run(db, p.id, triggered_at=past)
        make_result(db, r.id, llm="openai", mentioned=True)
        make_result(db, r.id, llm="gemini", mentioned=False)

        resp = client.get("/api/trends/dashboard?period=365")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 1
        assert all(0 <= d["mention_rate"] <= 100 for d in data)

    def test_period_filter_restricts_results(self, client, db):
        """period=1 should not error; just return up to 1 day of data."""
        resp = client.get("/api/trends/dashboard?period=1")
        assert resp.status_code == 200

    def test_from_to_date_filter(self, client, db):
        resp = client.get("/api/trends/dashboard?from_date=2000-01-01&to_date=2000-01-02")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_error_results_excluded(self, client, db):
        """Results with errors must not count toward total_results for that day."""
        from datetime import datetime, timezone, timedelta
        past_dt = datetime(2010, 6, 15, 12, 0, tzinfo=timezone.utc)
        p = make_prompt(db, label="DashTrend-err")
        r = make_run(db, p.id, triggered_at=past_dt)
        make_result(db, r.id, llm="openai", mentioned=True, error="timeout")

        resp = client.get("/api/trends/dashboard?from_date=2010-06-15&to_date=2010-06-15")
        assert resp.status_code == 200
        # The errored result is excluded, so that day has 0 total_results
        data = resp.json()["data"]
        assert data == [] or all(d["total_results"] == 0 for d in data)


class TestPromptTrend:

    def test_known_prompt_returns_series(self, client, db):
        p = make_prompt(db, label="PromptTrend-known")
        r = make_run(db, p.id)
        make_result(db, r.id, llm="openai", mentioned=True)
        make_result(db, r.id, llm="gemini", mentioned=False)

        resp = client.get(f"/api/trends/prompt/{p.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["prompt_id"] == p.id
        assert "series" in body
        assert "openai" in body["series"]
        assert "gemini" in body["series"]
        assert "runs" in body

    def test_unknown_prompt_returns_error(self, client, db):
        resp = client.get("/api/trends/prompt/999999")
        assert resp.status_code == 200
        assert "error" in resp.json()

    def test_series_mention_rate_correct(self, client, db):
        p = make_prompt(db, label="PromptTrend-rate")
        r = make_run(db, p.id)
        make_result(db, r.id, llm="openai", mentioned=True)

        resp = client.get(f"/api/trends/prompt/{p.id}")
        series = resp.json()["series"]["openai"]
        assert len(series) >= 1
        assert series[0]["mention_rate"] == 100.0

    def test_run_history_included(self, client, db):
        p = make_prompt(db, label="PromptTrend-hist")
        make_run(db, p.id)
        make_run(db, p.id)

        resp = client.get(f"/api/trends/prompt/{p.id}")
        runs = resp.json()["runs"]
        assert len(runs) >= 2

    def test_metadata_fields_present(self, client, db):
        p = make_prompt(db, label="PromptTrend-meta", query_type="problem", variant_group="vg1")

        resp = client.get(f"/api/trends/prompt/{p.id}")
        body = resp.json()
        assert body["label"] == "PromptTrend-meta"
        assert body["query_type"] == "problem"
        assert body["variant_group"] == "vg1"


class TestPerLlmTrend:

    def test_returns_per_llm_series(self, client, db):
        p = make_prompt(db, label="PerLLM-series")
        r = make_run(db, p.id)
        make_result(db, r.id, llm="openai", mentioned=True)
        make_result(db, r.id, llm="gemini", mentioned=False)
        make_result(db, r.id, llm="perplexity", mentioned=True)

        resp = client.get("/api/trends/per-llm?period=365")
        assert resp.status_code == 200
        body = resp.json()
        assert "series" in body
        for llm in ("openai", "gemini", "perplexity"):
            assert llm in body["series"]

    def test_period_param_accepted(self, client, db):
        for period in (7, 14, 30, 90):
            resp = client.get(f"/api/trends/per-llm?period={period}")
            assert resp.status_code == 200

    def test_future_date_range_returns_empty_series(self, client, db):
        # Use year 3000 — no test data will ever exist there
        resp = client.get("/api/trends/per-llm?from_date=3000-01-01&to_date=3000-12-31")
        assert resp.status_code == 200
        body = resp.json()
        for series in body["series"].values():
            assert series == []


class TestSentimentTrend:

    def test_returns_sentiment_pcts(self, client, db):
        p = make_prompt(db, label="Sent-trend")
        r = make_run(db, p.id)
        make_result(db, r.id, llm="openai", sentiment="positive")
        make_result(db, r.id, llm="gemini", sentiment="negative")
        make_result(db, r.id, llm="perplexity", sentiment="neutral")

        resp = client.get("/api/trends/sentiment?from_date=2010-01-01&to_date=2040-01-01")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) >= 1
        for d in data:
            assert "positive_pct" in d
            assert "neutral_pct" in d
            assert "negative_pct" in d
            total = d["positive_pct"] + d["neutral_pct"] + d["negative_pct"]
            assert abs(total - 100.0) < 1.0  # should sum to ~100%

    def test_empty_range_returns_empty_list(self, client, db):
        resp = client.get("/api/trends/sentiment?from_date=2000-01-01&to_date=2000-01-02")
        assert resp.status_code == 200
        assert resp.json()["data"] == []


class TestShareOfVoice:

    def test_returns_brand_and_competitors(self, client, db, monkeypatch):
        monkeypatch.setenv("TARGET_COMPANY", "Acme")
        monkeypatch.setenv("COMPETITORS", "RivalA,RivalB")

        p = make_prompt(db, label="SoV-test")
        r = make_run(db, p.id)
        make_result(db, r.id, llm="openai", mentioned=True,
                    competitors_mentioned='["RivalA"]')
        make_result(db, r.id, llm="gemini", mentioned=False,
                    competitors_mentioned='["RivalB"]')

        resp = client.get("/api/trends/share-of-voice")
        assert resp.status_code == 200
        body = resp.json()
        assert "brand" in body
        assert "competitors" in body
        assert body["brand"]["name"] == "Acme"
        assert body["total_results"] >= 2

    def test_no_data_returns_zero_rates(self, client, db, monkeypatch):
        monkeypatch.setenv("TARGET_COMPANY", "Acme")
        monkeypatch.setenv("COMPETITORS", "")

        resp = client.get("/api/trends/share-of-voice?from_date=2000-01-01&to_date=2000-01-02")
        assert resp.status_code == 200
        body = resp.json()
        assert body["brand"]["mention_rate"] == 0
        assert body["total_results"] == 0

    def test_competitor_mention_rates_calculated(self, client, db, monkeypatch):
        monkeypatch.setenv("TARGET_COMPANY", "Acme")
        monkeypatch.setenv("COMPETITORS", "RivalX")

        p = make_prompt(db, label="SoV-comp")
        r = make_run(db, p.id)
        make_result(db, r.id, llm="openai", mentioned=False,
                    competitors_mentioned='["RivalX"]')

        resp = client.get("/api/trends/share-of-voice?period=365")
        assert resp.status_code == 200
        comps = resp.json()["competitors"]
        rival = next((c for c in comps if c["name"] == "RivalX"), None)
        assert rival is not None
        assert rival["mentions"] >= 1
