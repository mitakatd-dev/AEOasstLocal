from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from datetime import datetime, timezone

import os

from app.database import get_db
from app.models import Run, Result, Prompt
from app.services.insights import generate_insights
from app.services.narrative import build_narrative_report

router = APIRouter(prefix="/api/stats", tags=["stats"])

LLM_NAMES = ["openai", "gemini", "perplexity"]

# Pricing per 1M tokens
LLM_PRICING = {
    "openai": {"input": 2.50, "output": 10.00, "model": "GPT-4o"},
    "gemini": {"input": 0.075, "output": 0.30, "model": "Gemini 1.5 Flash"},
    "perplexity": {"input": 1.00, "output": 1.00, "model": "Sonar"},
}


def _parse_dt(val: str, eod: bool = False) -> str:
    """Accept YYYY-MM-DD or full datetime string; return SQLite-comparable string."""
    if len(val) == 10:  # date-only → add time boundary
        return f"{val} {'23:59:59' if eod else '00:00:00'}"
    return val  # already has time component


def _apply_date_filter(q, from_date: Optional[str], to_date: Optional[str]):
    """Apply from_date / to_date filters to a query that already has Run in scope."""
    if from_date:
        q = q.filter(Run.triggered_at >= _parse_dt(from_date))
    if to_date:
        q = q.filter(Run.triggered_at <= _parse_dt(to_date, eod=True))
    return q


@router.get("/")
def get_stats(
    from_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD (inclusive)"),
    to_date: Optional[str] = Query(None, description="End date YYYY-MM-DD (inclusive)"),
    db: Session = Depends(get_db),
):
    # ── Run counts ────────────────────────────────────────────────────────────
    run_q = db.query(Run)
    run_q = _apply_date_filter(run_q, from_date, to_date)

    total_runs = run_q.count()
    successful_runs = run_q.filter(Run.status.in_(["completed", "partial"])).count()
    failed_runs = run_q.filter(Run.status == "failed").count()

    # ── Results within the same date window — join Run for collection_method ──
    result_q = db.query(Result, Run).join(Run, Run.id == Result.run_id)
    result_q = _apply_date_filter(result_q, from_date, to_date)
    result_rows = result_q.all()   # list of (Result, Run) tuples

    # Flat list of Result objects for backward-compat (competitor counts etc.)
    all_results = [r for r, _ in result_rows]

    # ── Cost & token totals (API runs only — browser runs have no tokens) ──────
    total_cost = 0.0
    total_tokens_all = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0

    per_llm = {}
    for llm in LLM_NAMES:
        # Split by collection method
        llm_rows = [(r, run) for r, run in result_rows if r.llm == llm]
        api_results    = [r for r, run in llm_rows if (run.collection_method or "api") == "api"]
        browser_results = [r for r, run in llm_rows if (run.collection_method or "api") == "browser"]

        valid_api     = [r for r in api_results     if not r.error]
        valid_browser = [r for r in browser_results if not r.error]
        valid_all     = valid_api + valid_browser
        errored_all   = [r for r in api_results + browser_results if r.error]

        # Mention rates — overall and per method
        mentioned_all     = sum(1 for r in valid_all     if r.mentioned)
        mentioned_api     = sum(1 for r in valid_api     if r.mentioned)
        mentioned_browser = sum(1 for r in valid_browser if r.mentioned)
        mention_rate         = round(mentioned_all     / len(valid_all)     * 100, 1) if valid_all     else 0
        api_mention_rate     = round(mentioned_api     / len(valid_api)     * 100, 1) if valid_api     else 0
        browser_mention_rate = round(mentioned_browser / len(valid_browser) * 100, 1) if valid_browser else 0

        positions  = [r.position_score for r in valid_all if r.mentioned and r.position_score is not None]
        avg_position = round(sum(positions) / len(positions), 3) if positions else None

        sentiments = {"positive": 0, "neutral": 0, "negative": 0}
        for r in valid_all:
            if r.sentiment in sentiments:
                sentiments[r.sentiment] += 1

        # Cost & tokens: API runs only (browser runs use the web UI — no token cost)
        llm_cost              = sum(r.cost_usd         or 0 for r in api_results)
        llm_prompt_tokens     = sum(r.prompt_tokens    or 0 for r in api_results)
        llm_completion_tokens = sum(r.completion_tokens or 0 for r in api_results)
        llm_total_tokens      = sum(r.total_tokens     or 0 for r in api_results)
        avg_latency = round(sum(r.latency_ms for r in valid_all) / len(valid_all)) if valid_all else 0

        total_cost            += llm_cost
        total_tokens_all      += llm_total_tokens
        total_prompt_tokens   += llm_prompt_tokens
        total_completion_tokens += llm_completion_tokens

        per_llm[llm] = {
            "model": LLM_PRICING[llm]["model"],
            "total_calls":           len(api_results) + len(browser_results),
            "api_calls":             len(api_results),
            "browser_calls":         len(browser_results),
            "successful":            len(valid_all),
            "errors":                len(errored_all),
            "mention_rate":          mention_rate,
            "api_mention_rate":      api_mention_rate,
            "browser_mention_rate":  browser_mention_rate,
            "avg_position":          avg_position,
            "sentiments":            sentiments,
            "avg_latency_ms":        avg_latency,
            # Token / cost fields apply to API calls only
            "prompt_tokens":         llm_prompt_tokens,
            "completion_tokens":     llm_completion_tokens,
            "total_tokens":          llm_total_tokens,
            "cost_usd":              round(llm_cost, 6),
            "avg_cost_per_call":     round(llm_cost / len(valid_api), 6) if valid_api else 0,
            "pricing":               LLM_PRICING[llm],
        }

    # ── Competitor leaderboard ─────────────────────────────────────────────────
    competitor_counts = {}
    for r in all_results:
        if not r.error and r.competitors_mentioned:
            import json
            try:
                comps = json.loads(r.competitors_mentioned)
                for c in comps:
                    competitor_counts[c] = competitor_counts.get(c, 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass
    top_competitors = sorted(competitor_counts.items(), key=lambda x: -x[1])[:10]

    return {
        "total_runs": total_runs,
        "successful_runs": successful_runs,
        "failed_runs": failed_runs,
        "per_llm": per_llm,
        "cost": {
            "total_usd": round(total_cost, 4),
            "total_tokens": total_tokens_all,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
        },
        "top_competitors": [{"name": c, "mentions": n} for c, n in top_competitors],
        # echo back for the UI
        "from_date": from_date,
        "to_date": to_date,
    }


@router.get("/insights")
def get_insights(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    target = os.getenv("TARGET_COMPANY", "")
    return generate_insights(target, db, from_date=from_date, to_date=to_date)


@router.get("/narrative")
def get_narrative(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    target = os.getenv("TARGET_COMPANY", "")
    competitors_str = os.getenv("COMPETITORS", "")
    competitors = [c.strip() for c in competitors_str.split(",") if c.strip()]
    return build_narrative_report(target, competitors, db, from_date=from_date, to_date=to_date)
