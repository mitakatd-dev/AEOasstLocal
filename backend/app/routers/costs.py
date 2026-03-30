"""
Cost aggregation endpoints — local edition.

Data sources:
  - API token costs: exact, from results.cost_usd
  - Proxy cost:      real via Brightdata API when BRIGHTDATA_API_KEY is set;
                     falls back to estimate (sessions × 3MB × $3/GB)
  - Infra cost:      $0 — running on your local machine, no cloud compute charges

Brightdata env vars (set via Settings UI or .env):
  BRIGHTDATA_API_KEY  — API token (Bearer auth)
  BRIGHTDATA_ZONE     — zone name to query (default: "residential_proxy")
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timezone, timedelta

import requests as _requests

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Run, Result, WorkerBatch

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/costs", tags=["costs"])

# ── Proxy pricing ─────────────────────────────────────────────────────────────
_PROXY_MB_PER_SESSION = 3.0   # estimated MB per browser session
_PROXY_USD_PER_GB     = 3.0   # Brightdata residential proxy rate


def _proxy_cost(session_count: int) -> float:
    gb = (session_count * _PROXY_MB_PER_SESSION) / 1024
    return round(gb * _PROXY_USD_PER_GB, 4)


# ── Brightdata live cost fetch ─────────────────────────────────────────────────

def _brightdata_costs() -> dict | None:
    api_key = os.getenv("BRIGHTDATA_API_KEY", "").strip()
    if not api_key:
        return None

    zone = os.getenv("BRIGHTDATA_ZONE", "residential_proxy")
    headers = {"Authorization": f"Bearer {api_key}"}
    base_url = "https://api.brightdata.com"
    result: dict = {"is_real": True}

    try:
        r = _requests.get(f"{base_url}/customer/balance", headers=headers, timeout=8)
        if r.ok:
            data = r.json()
            result["balance_usd"] = data.get("balance") or data.get("usd") or 0.0
    except Exception as exc:
        log.debug("Brightdata balance fetch failed: %s", exc)

    try:
        r = _requests.get(f"{base_url}/zone/bw", params={"zone": zone}, headers=headers, timeout=8)
        if r.ok:
            data = r.json()
            bytes_used = data.get("bytes") or data.get("bw") or 0
            result["zone_gb"] = round(bytes_used / (1024 ** 3), 4)
    except Exception as exc:
        log.debug("Brightdata bw fetch failed: %s", exc)

    try:
        r = _requests.get(f"{base_url}/zone/cost", params={"zone": zone}, headers=headers, timeout=8)
        if r.ok:
            data = r.json()
            result["zone_cost_usd"] = data.get("cost") or data.get("usd") or 0.0
    except Exception as exc:
        log.debug("Brightdata zone cost fetch failed: %s", exc)

    return result if len(result) > 1 else None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/summary")
def cost_summary(
    days: int = Query(30, description="Rolling window in days"),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Exact API token cost from stored results
    api_cost = (
        db.query(func.coalesce(func.sum(Result.cost_usd), 0))
        .join(Run, Result.run_id == Run.id)
        .filter(Run.triggered_at >= since)
        .scalar() or 0.0
    )

    browser_sessions = db.query(func.count(WorkerBatch.id)).scalar() or 0

    brightdata  = _brightdata_costs()
    proxy_real  = brightdata is not None and "zone_cost_usd" in brightdata
    proxy_cost  = round(brightdata["zone_cost_usd"], 4) if proxy_real else _proxy_cost(browser_sessions)
    proxy_gb    = brightdata.get("zone_gb") if brightdata else None
    bd_balance  = brightdata.get("balance_usd") if brightdata else None
    proxy_note  = (
        f"Real from Brightdata API ({proxy_gb:.2f} GB used)" if proxy_real
        else f"Estimated at {_PROXY_MB_PER_SESSION}MB/session × ${_PROXY_USD_PER_GB}/GB"
    )

    per_llm = (
        db.query(
            Result.llm,
            func.coalesce(func.sum(Result.cost_usd), 0),
            func.count(Result.id),
        )
        .join(Run, Result.run_id == Run.id)
        .filter(Run.triggered_at >= since)
        .group_by(Result.llm)
        .all()
    )

    browser_results = (
        db.query(func.count(Run.id))
        .filter(Run.collection_method == "browser", Run.triggered_at >= since)
        .scalar() or 0
    )
    api_results = (
        db.query(func.count(Run.id))
        .filter(Run.collection_method == "api", Run.triggered_at >= since)
        .scalar() or 0
    )

    total = round(api_cost + proxy_cost, 4)  # infra is $0 locally

    return {
        "window_days":       days,
        "total_usd":         total,
        "breakdown": {
            "api_tokens_usd":  round(api_cost, 4),
            "proxy_usd":       proxy_cost,
            "infra_usd":       0.0,    # local machine — no cloud compute cost
            "job_compute_usd": 0.0,
        },
        "per_llm": [
            {"llm": llm, "cost_usd": round(cost, 4), "result_count": count}
            for llm, cost, count in per_llm
        ],
        "browser_sessions":       browser_sessions,
        "browser_results":        browser_results,
        "api_results":            api_results,
        "proxy_source":           "brightdata_api" if proxy_real else "estimate",
        "brightdata_balance_usd": bd_balance,
        "infra_source":           "local",
        "infra_detail":           {"note": "Running locally — no infrastructure cost"},
        "note": {
            "proxy": proxy_note,
            "infra": "No cloud infrastructure cost — running on local machine",
        },
    }


@router.get("/sessions")
def cost_by_session(
    limit: int = Query(20),
    days: int = Query(90),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    session_costs = (
        db.query(
            Run.session_id,
            Run.collection_method,
            func.min(Run.triggered_at).label("started_at"),
            func.count(Result.id).label("result_count"),
            func.sum(Result.cost_usd).label("api_cost"),
            func.sum(Result.latency_ms).label("total_latency_ms"),
        )
        .join(Result, Result.run_id == Run.id)
        .filter(Run.session_id.isnot(None), Run.triggered_at >= since)
        .group_by(Run.session_id, Run.collection_method)
        .order_by(func.min(Run.triggered_at).desc())
        .limit(limit)
        .all()
    )

    rows = []
    for sid, method, started_at, count, api_cost, total_latency_ms in session_costs:
        api_cost = api_cost or 0.0
        proxy    = _proxy_cost(1) if method == "browser" else 0.0
        total    = round(api_cost + proxy, 4)
        rows.append({
            "session_id":        sid,
            "collection_method": method,
            "started_at":        started_at.isoformat() if started_at else None,
            "result_count":      count,
            "api_cost_usd":      round(api_cost, 4),
            "proxy_cost_usd":    proxy,
            "total_usd":         total,
            "avg_latency_ms":    round(total_latency_ms / count, 0) if count else 0,
        })

    return {"sessions": rows}


@router.get("/daily")
def daily_costs(
    days: int = Query(30),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    daily = (
        db.query(
            func.date(Run.triggered_at).label("day"),
            func.coalesce(func.sum(Result.cost_usd), 0).label("api_cost"),
            func.count(Result.id).label("result_count"),
        )
        .join(Result, Result.run_id == Run.id)
        .filter(Run.triggered_at >= since)
        .group_by(func.date(Run.triggered_at))
        .order_by(func.date(Run.triggered_at).asc())
        .all()
    )

    return {
        "daily": [
            {
                "date":         str(row.day),
                "api_cost_usd": round(row.api_cost, 4),
                "result_count": row.result_count,
                "infra_usd":    0.0,  # local — no infra cost
            }
            for row in daily
        ]
    }
