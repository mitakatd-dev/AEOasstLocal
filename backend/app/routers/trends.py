from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, and_
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
import json
import os

from app.database import get_db
from app.models import Run, Result, Prompt

router = APIRouter(prefix="/api/trends", tags=["trends"])

LLM_NAMES = ["openai", "gemini", "perplexity"]


def _parse_dt(val: str, eod: bool = False) -> str:
    """Accept YYYY-MM-DD or full datetime string; return SQLite-comparable string."""
    if len(val) == 10:
        return f"{val} {'23:59:59' if eod else '00:00:00'}"
    return val


def _date_window(
    period: int,
    from_date: Optional[str],
    to_date: Optional[str],
) -> Tuple[str, str]:
    """
    Return (cutoff_str, ceiling_str) for SQLite WHERE clauses.
    from_date/to_date (date or datetime strings) win over rolling period.
    """
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if from_date:
        cutoff = _parse_dt(from_date)
    else:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=period)).strftime("%Y-%m-%d %H:%M:%S")

    ceiling = _parse_dt(to_date, eod=True) if to_date else now_str
    return cutoff, ceiling


@router.get("/dashboard")
def dashboard_trend(
    period: int = Query(30, ge=1, le=365),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Overall mention rate per day."""
    cutoff, ceiling = _date_window(period, from_date, to_date)

    rows = (
        db.query(
            func.date(Run.triggered_at).label("day"),
            func.count(Result.id).label("total"),
            func.sum(case((and_(Result.mentioned == True, Result.error.is_(None)), 1), else_=0)).label("mentioned"),
        )
        .join(Result, Result.run_id == Run.id)
        .filter(Run.triggered_at >= cutoff, Run.triggered_at <= ceiling, Result.error.is_(None))  # noqa: E501
        .group_by(func.date(Run.triggered_at))
        .order_by(func.date(Run.triggered_at))
        .all()
    )

    return {
        "period": period,
        "from_date": from_date,
        "to_date": to_date,
        "data": [
            {
                "date": r.day,
                "mention_rate": round(r.mentioned / r.total * 100, 1) if r.total else 0,
                "total_results": r.total,
            }
            for r in rows
        ],
    }


@router.get("/prompt/{prompt_id}")
def prompt_trend(prompt_id: int, db: Session = Depends(get_db)):
    """Mention rate per LLM per run date for a given prompt."""
    prompt = db.query(Prompt).get(prompt_id)
    if not prompt:
        return {"error": "Prompt not found"}

    rows = (
        db.query(
            func.date(Run.triggered_at).label("day"),
            Result.llm,
            func.count(Result.id).label("total"),
            func.sum(case((Result.mentioned == True, 1), else_=0)).label("mentioned"),
            func.avg(Result.position_score).label("avg_position"),
            func.sum(case((Result.sentiment == "positive", 1), else_=0)).label("positive"),
            func.sum(case((Result.sentiment == "neutral", 1), else_=0)).label("neutral"),
            func.sum(case((Result.sentiment == "negative", 1), else_=0)).label("negative"),
        )
        .join(Result, Result.run_id == Run.id)
        .filter(Run.prompt_id == prompt_id, Result.error.is_(None))
        .group_by(func.date(Run.triggered_at), Result.llm)
        .order_by(func.date(Run.triggered_at))
        .all()
    )

    runs_data = (
        db.query(Run)
        .filter(Run.prompt_id == prompt_id)
        .order_by(Run.triggered_at.desc())
        .all()
    )

    series = {llm: [] for llm in LLM_NAMES}
    for r in rows:
        if r.llm in series:
            series[r.llm].append({
                "date": r.day,
                "mention_rate": round(r.mentioned / r.total * 100, 1) if r.total else 0,
                "avg_position": round(r.avg_position, 3) if r.avg_position else None,
                "sentiment": {
                    "positive": r.positive or 0,
                    "neutral": r.neutral or 0,
                    "negative": r.negative or 0,
                },
            })

    run_history = []
    for run in runs_data:
        results = []
        for res in run.results:
            results.append({
                "llm": res.llm,
                "mentioned": res.mentioned,
                "sentiment": res.sentiment,
                "position_score": res.position_score,
                "error": res.error,
            })
        run_history.append({
            "id": run.id,
            "triggered_at": run.triggered_at.isoformat() if run.triggered_at else None,
            "status": run.status,
            "results": results,
        })

    return {
        "prompt_id": prompt_id,
        "label": prompt.label,
        "text": prompt.text,
        "query_type": prompt.query_type,
        "variant_group": prompt.variant_group,
        "series": series,
        "runs": run_history,
    }


@router.get("/per-llm")
def per_llm_trend(
    period: int = Query(30, ge=1, le=365),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Mention rate over time per LLM engine."""
    cutoff, ceiling = _date_window(period, from_date, to_date)

    rows = (
        db.query(
            func.date(Run.triggered_at).label("day"),
            Result.llm,
            func.count(Result.id).label("total"),
            func.sum(case((Result.mentioned == True, 1), else_=0)).label("mentioned"),
        )
        .join(Result, Result.run_id == Run.id)
        .filter(Run.triggered_at >= cutoff, Run.triggered_at <= ceiling, Result.error.is_(None))  # noqa: E501
        .group_by(func.date(Run.triggered_at), Result.llm)
        .order_by(func.date(Run.triggered_at))
        .all()
    )

    series = {llm: [] for llm in LLM_NAMES}
    for r in rows:
        if r.llm in series:
            series[r.llm].append({
                "date": r.day,
                "mention_rate": round(r.mentioned / r.total * 100, 1) if r.total else 0,
                "total": r.total,
            })

    return {"period": period, "from_date": from_date, "to_date": to_date, "series": series}


@router.get("/sentiment")
def sentiment_trend(
    period: int = Query(30, ge=1, le=365),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Sentiment distribution over time."""
    cutoff, ceiling = _date_window(period, from_date, to_date)

    rows = (
        db.query(
            func.date(Run.triggered_at).label("day"),
            func.count(Result.id).label("total"),
            func.sum(case((Result.sentiment == "positive", 1), else_=0)).label("positive"),
            func.sum(case((Result.sentiment == "neutral", 1), else_=0)).label("neutral"),
            func.sum(case((Result.sentiment == "negative", 1), else_=0)).label("negative"),
        )
        .join(Result, Result.run_id == Run.id)
        .filter(Run.triggered_at >= cutoff, Run.triggered_at <= ceiling, Result.error.is_(None))  # noqa: E501
        .group_by(func.date(Run.triggered_at))
        .order_by(func.date(Run.triggered_at))
        .all()
    )

    return {
        "period": period,
        "from_date": from_date,
        "to_date": to_date,
        "data": [
            {
                "date": r.day,
                "positive_pct": round(r.positive / r.total * 100, 1) if r.total else 0,
                "neutral_pct": round(r.neutral / r.total * 100, 1) if r.total else 0,
                "negative_pct": round(r.negative / r.total * 100, 1) if r.total else 0,
                "total": r.total,
            }
            for r in rows
        ],
    }


@router.get("/share-of-voice")
def share_of_voice(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Brand mention rate vs competitor mention rates."""
    target = os.getenv("TARGET_COMPANY", "")
    competitors_str = os.getenv("COMPETITORS", "")
    competitor_list = [c.strip() for c in competitors_str.split(",") if c.strip()]

    q = db.query(Result).join(Run, Run.id == Result.run_id).filter(Result.error.is_(None))
    if from_date:
        q = q.filter(Run.triggered_at >= _parse_dt(from_date))
    if to_date:
        q = q.filter(Run.triggered_at <= _parse_dt(to_date, eod=True))
    valid_results = q.all()

    total = len(valid_results)
    if total == 0:
        return {"brand": {"name": target, "mention_rate": 0, "mentions": 0}, "competitors": [], "total_results": 0}

    brand_mentions = sum(1 for r in valid_results if r.mentioned)
    brand_rate = round(brand_mentions / total * 100, 1)

    comp_counts = {c: 0 for c in competitor_list}
    for r in valid_results:
        if r.competitors_mentioned:
            try:
                comps = json.loads(r.competitors_mentioned)
                for c in comps:
                    if c in comp_counts:
                        comp_counts[c] += 1
            except (json.JSONDecodeError, TypeError):
                pass

    competitors_data = [
        {"name": c, "mention_rate": round(count / total * 100, 1), "mentions": count}
        for c, count in sorted(comp_counts.items(), key=lambda x: -x[1])
    ]

    return {
        "brand": {"name": target, "mention_rate": brand_rate, "mentions": brand_mentions},
        "competitors": competitors_data,
        "total_results": total,
        "from_date": from_date,
        "to_date": to_date,
    }
