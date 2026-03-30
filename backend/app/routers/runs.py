from __future__ import annotations

import csv
import io
import json
import threading
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel

from app.database import get_db, SessionLocal
from app.models import Run, Prompt, Result, WorkerBatch, Citation
from app.services.runner import execute_run
from app.auth import require_admin

router = APIRouter(prefix="/api/runs", tags=["runs"])

VALID_PLATFORMS = {"openai", "gemini", "perplexity"}


# ── Pydantic models ───────────────────────────────────────────────────────────

class RunTrigger(BaseModel):
    prompt_ids:        List[int]
    platforms:         Optional[List[str]] = None   # None = all three
    collection_method: Optional[str]       = "api"
    session_id:        Optional[str]       = None   # auto-generated if omitted


class ResultOut(BaseModel):
    id:                   int
    llm:                  str
    raw_response:         Optional[str]
    mentioned:            bool
    position_score:       Optional[float]
    sentiment:            Optional[str]
    competitors_mentioned: List[str]
    error:                Optional[str]
    latency_ms:           int
    prompt_tokens:        int = 0
    completion_tokens:    int = 0
    total_tokens:         int = 0
    cost_usd:             float = 0.0

    class Config:
        from_attributes = True


class RunOut(BaseModel):
    id:                int
    prompt_id:         int
    prompt_label:      Optional[str] = None
    triggered_at:      Optional[str] = None
    status:            str
    session_id:        Optional[str] = None
    collection_method: Optional[str] = "api"
    results:           List[ResultOut] = []

    class Config:
        from_attributes = True


# ── Background execution ──────────────────────────────────────────────────────

def _run_in_background(runs_to_execute, platforms=None):
    import asyncio as _asyncio

    async def _do_runs():
        for rc in runs_to_execute:
            db = SessionLocal()
            try:
                await execute_run(rc["run_id"], rc["prompt_text"], db, platforms)
            except Exception:
                run = db.query(Run).filter(Run.id == rc["run_id"]).first()
                if run and run.status == "running":
                    run.status = "failed"
                    db.commit()
            finally:
                db.close()

    loop = _asyncio.new_event_loop()
    loop.run_until_complete(_do_runs())
    loop.close()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/", status_code=201)
def trigger_runs(body: RunTrigger, db: Session = Depends(get_db)):
    """
    Trigger API runs for the given prompt IDs.
    Optionally restrict to specific platforms and tag with a session_id.
    """
    # Validate platforms
    platforms = None
    if body.platforms:
        invalid = set(body.platforms) - VALID_PLATFORMS
        if invalid:
            raise HTTPException(400, f"Unknown platforms: {invalid}. Valid: {VALID_PLATFORMS}")
        platforms = list(body.platforms)

    session_id = body.session_id or str(uuid.uuid4())

    runs_created = []
    for pid in body.prompt_ids:
        prompt = db.query(Prompt).filter(Prompt.id == pid).first()
        if not prompt:
            continue
        run = Run(
            prompt_id=pid,
            status="running",
            session_id=session_id,
            collection_method=body.collection_method or "api",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        runs_created.append({"run_id": run.id, "prompt_text": prompt.text})

    if runs_created:
        t = threading.Thread(
            target=_run_in_background,
            args=(runs_created, platforms),
            daemon=True,
        )
        t.start()

    return {
        "run_ids":    [r["run_id"] for r in runs_created],
        "session_id": session_id,
        "count":      len(runs_created),
    }


@router.post("/run-all", status_code=201)
def run_all_prompts(
    query_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Run all prompts (optionally filtered by type) against all platforms via API."""
    q = db.query(Prompt)
    if query_type:
        q = q.filter(Prompt.query_type == query_type)
    all_prompts = q.all()

    if not all_prompts:
        return {"run_ids": [], "count": 0, "session_id": None}

    session_id    = str(uuid.uuid4())
    runs_created  = []
    for prompt in all_prompts:
        run = Run(
            prompt_id=prompt.id,
            status="running",
            session_id=session_id,
            collection_method="api",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        runs_created.append({"run_id": run.id, "prompt_text": prompt.text})

    if runs_created:
        t = threading.Thread(target=_run_in_background, args=(runs_created, None), daemon=True)
        t.start()

    return {"run_ids": [r["run_id"] for r in runs_created], "count": len(runs_created), "session_id": session_id}


# ── Batch detection ───────────────────────────────────────────────────────────

_BATCH_GAP_SECONDS = 30 * 60  # runs separated by > 30 min = different batch


def _detect_batches(db: Session) -> list:
    """
    Cluster all runs into natural batches by time proximity.
    Gap > 30 min between consecutive runs (by triggered_at) = new batch.
    Future runs with session_id are also respected — same session_id always
    lands in the same batch even if triggered close to another session.
    Returns list of batch dicts, newest first.
    """
    runs = (
        db.query(Run)
        .filter(Run.triggered_at.isnot(None))
        .order_by(Run.triggered_at.asc())
        .all()
    )
    if not runs:
        return []

    # Build clusters
    clusters: list[list[Run]] = []
    current: list[Run] = [runs[0]]

    for run in runs[1:]:
        prev = current[-1]
        gap = (run.triggered_at - prev.triggered_at).total_seconds()
        same_session = (
            run.session_id is not None
            and run.session_id == prev.session_id
        )
        # Explicit different session IDs always = new batch, regardless of time gap.
        # Time-based gap is only used for pre-session-id legacy runs (session_id=None).
        different_sessions = (
            run.session_id is not None
            and prev.session_id is not None
            and run.session_id != prev.session_id
        )
        if different_sessions:
            clusters.append(current)
            current = [run]
        elif same_session or gap <= _BATCH_GAP_SECONDS:
            current.append(run)
        else:
            clusters.append(current)
            current = [run]
    clusters.append(current)

    # Sort newest-first
    clusters.sort(key=lambda c: c[0].triggered_at, reverse=True)

    result = []
    for i, cluster in enumerate(clusters):
        from datetime import timedelta as _td
        start = min(r.triggered_at for r in cluster)
        end   = max(r.triggered_at for r in cluster) + _td(seconds=1)  # pad for fractional-second timestamps

        # Collect platforms/methods without hitting results (avoid N+1)
        methods = list({r.collection_method or "api" for r in cluster})
        run_ids = {r.id for r in cluster}

        # Per-LLM result counts (used for live progress breakdown in UI)
        result_count_rows = (
            db.query(Result.llm, func.count(Result.id))
            .filter(Result.run_id.in_(run_ids))
            .group_by(Result.llm)
            .all()
        )
        platform_progress = {
            row[0]: {"completed": row[1], "total": len(cluster)}
            for row in result_count_rows
        }
        platforms = sorted(platform_progress.keys()) if platform_progress else []

        completed          = sum(1 for r in cluster if r.status in ("completed", "partial"))
        failed             = sum(1 for r in cluster if r.status == "failed")
        failed_prompt_ids  = list({r.prompt_id for r in cluster if r.status == "failed"})

        # Session metadata — for linking to the session report page
        session_ids = list({r.session_id for r in cluster if r.session_id})
        # If the whole batch came from one session, expose it directly for linking
        primary_session_id = session_ids[0] if len(session_ids) == 1 else None

        # Duration in minutes from first to last run
        duration_mins = round((end - start - _td(seconds=1)).total_seconds() / 60, 1)

        # Avg latency across all results in this batch (browser runs have real latency_ms)
        avg_latency_row = (
            db.query(func.avg(Result.latency_ms))
            .filter(Result.run_id.in_(run_ids), Result.latency_ms > 0)
            .scalar()
        )
        avg_latency_ms = int(avg_latency_row) if avg_latency_row else 0

        # Total pause time from WorkerBatches linked to the same session(s)
        total_paused_s = 0
        if session_ids:
            paused_batches = (
                db.query(WorkerBatch)
                .filter(WorkerBatch.session_id.in_(list(session_ids)))
                .all()
            )
            total_paused_s = sum(b.total_paused_s or 0 for b in paused_batches)

        # Human-readable label: show method badge if browser run
        method_tag = " · 🌐 Web" if "browser" in methods else ""
        label = f"{start.strftime('%b %d %H:%M')} · {len(cluster)} runs{method_tag}"

        result.append({
            "batch_index":        i + 1,
            "label":              label,
            "from_dt":            start.strftime("%Y-%m-%d %H:%M:%S"),
            "to_dt":              end.strftime("%Y-%m-%d %H:%M:%S"),
            "date":               start.strftime("%Y-%m-%d"),
            "started_at":         start.isoformat(),
            "run_count":          len(cluster),
            "completed":          completed,
            "failed":             failed,
            "failed_prompt_ids":  failed_prompt_ids,
            "platforms":          platforms,
            "platform_progress":  platform_progress,
            "methods":            methods,
            "session_ids":        session_ids,
            "primary_session_id": primary_session_id,
            "duration_mins":      duration_mins,
            "avg_latency_ms":     avg_latency_ms,
            "total_paused_s":     total_paused_s,
            "is_latest":          i == 0,
        })

    return result


@router.get("/batches")
def list_batches(db: Session = Depends(get_db)):
    """
    Return auto-detected run batches (clusters of runs within a 30-min window).
    Works for both historical runs (no session_id) and new runs (with session_id).
    """
    return _detect_batches(db)


# ── Sessions ──────────────────────────────────────────────────────────────────

@router.get("/sessions")
def list_sessions(
    method: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Return all research sessions (groups of runs triggered together).
    Each session summarises prompt count, platforms used, method, and status.
    """
    q = db.query(Run)
    if method:
        q = q.filter(Run.collection_method == method)
    all_runs = q.order_by(Run.triggered_at.desc()).all()

    # Group by session_id; runs without session_id each form their own pseudo-session
    sessions: dict = {}
    for run in all_runs:
        key = run.session_id or f"_solo_{run.id}"
        if key not in sessions:
            sessions[key] = {
                "session_id":        run.session_id or str(run.id),
                "triggered_at":      run.triggered_at.isoformat() if run.triggered_at else None,
                "collection_method": run.collection_method or "api",
                "runs":              [],
                "platforms":         set(),
                "statuses":          [],
            }
        sessions[key]["runs"].append(run)
        sessions[key]["statuses"].append(run.status)
        for res in run.results:
            sessions[key]["platforms"].add(res.llm)

    output = []
    for key, s in sessions.items():
        runs       = s["runs"]
        statuses   = s["statuses"]
        total      = len(runs)
        completed  = sum(1 for st in statuses if st in ("completed", "partial"))
        failed     = sum(1 for st in statuses if st == "failed")
        running    = sum(1 for st in statuses if st == "running")

        if running > 0:
            overall = "running"
        elif failed == total:
            overall = "failed"
        elif failed > 0 or any(st == "partial" for st in statuses):
            overall = "partial"
        else:
            overall = "completed"

        output.append({
            "session_id":        s["session_id"],
            "triggered_at":      s["triggered_at"],
            "collection_method": s["collection_method"],
            "prompt_count":      total,
            "platforms":         sorted(s["platforms"]),
            "completed":         completed,
            "failed":            failed,
            "total":             total,
            "status":            overall,
        })

    return output


@router.get("/sessions/{session_id}/results")
def session_results(session_id: str, db: Session = Depends(get_db)):
    """Return all runs + results for a session."""
    runs = db.query(Run).filter(Run.session_id == session_id).all()
    if not runs:
        raise HTTPException(404, "Session not found")

    output = []
    for run in runs:
        prompt = db.query(Prompt).filter(Prompt.id == run.prompt_id).first()
        output.append({
            "run_id":       run.id,
            "prompt_label": prompt.label if prompt else None,
            "prompt_text":  prompt.text  if prompt else None,
            "status":       run.status,
            "triggered_at": run.triggered_at.isoformat() if run.triggered_at else None,
            "results": [
                {
                    "llm":                   r.llm,
                    "mentioned":             r.mentioned,
                    "sentiment":             r.sentiment,
                    "position_score":        r.position_score,
                    "competitors_mentioned": json.loads(r.competitors_mentioned or "[]"),
                    "error":                 r.error,
                    "latency_ms":            r.latency_ms,
                    "cost_usd":              r.cost_usd,
                }
                for r in run.results
            ],
        })
    return output


@router.get("/sessions/{session_id}/export")
def export_session(session_id: str, db: Session = Depends(get_db)):
    """Export all results for a single session as CSV."""
    rows = (
        db.query(Result, Run, Prompt)
        .join(Run, Result.run_id == Run.id)
        .join(Prompt, Run.prompt_id == Prompt.id)
        .filter(Run.session_id == session_id)
        .order_by(Run.triggered_at)
        .all()
    )
    if not rows:
        raise HTTPException(404, "Session not found or has no results")

    return _build_csv_response(rows, f"session_{session_id}.csv")


@router.delete("/sessions/{session_id}", status_code=200)
def delete_session(session_id: str, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    """
    Delete all data for a session: Citations → Results → Runs → WorkerBatch.
    Admin only. Irreversible.
    """
    runs = db.query(Run).filter(Run.session_id == session_id).all()
    if not runs:
        raise HTTPException(404, "Session not found")

    run_ids = [r.id for r in runs]
    result_ids = [row[0] for row in db.query(Result.id).filter(Result.run_id.in_(run_ids)).all()]

    if result_ids:
        db.query(Citation).filter(Citation.result_id.in_(result_ids)).delete(synchronize_session=False)
    db.query(Result).filter(Result.run_id.in_(run_ids)).delete(synchronize_session=False)
    db.query(Run).filter(Run.session_id == session_id).delete(synchronize_session=False)
    db.query(WorkerBatch).filter(WorkerBatch.session_id == session_id).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "deleted_runs": len(run_ids)}


# ── Standard list / detail ────────────────────────────────────────────────────

@router.get("/export/csv")
def export_all_csv(db: Session = Depends(get_db)):
    rows = (
        db.query(Result, Run, Prompt)
        .join(Run, Result.run_id == Run.id)
        .join(Prompt, Run.prompt_id == Prompt.id)
        .order_by(Run.triggered_at.desc())
        .all()
    )
    return _build_csv_response(rows, "aeo_all_results.csv")


def _build_csv_response(rows, filename: str):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "session_id", "run_id", "prompt_label", "triggered_at",
        "collection_method", "llm", "mentioned", "position_score",
        "sentiment", "competitors_mentioned", "error",
        "latency_ms", "cost_usd", "raw_response",
    ])
    for result, run, prompt in rows:
        writer.writerow([
            run.session_id or "",
            run.id,
            prompt.label,
            run.triggered_at.isoformat() if run.triggered_at else "",
            run.collection_method or "api",
            result.llm,
            result.mentioned,
            result.position_score,
            result.sentiment,
            result.competitors_mentioned,
            result.error or "",
            result.latency_ms,
            result.cost_usd,
            (result.raw_response or "").replace("\n", " "),
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/", response_model=List[RunOut])
def list_runs(
    page:     int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    offset = (page - 1) * per_page
    runs   = (
        db.query(Run)
        .order_by(Run.triggered_at.desc())
        .offset(offset).limit(per_page).all()
    )
    return [_run_to_out(r, db) for r in runs]


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    return _run_to_out(run, db)


def _run_to_out(run: Run, db) -> RunOut:
    prompt = db.query(Prompt).filter(Prompt.id == run.prompt_id).first()
    return RunOut(
        id=run.id,
        prompt_id=run.prompt_id,
        prompt_label=prompt.label if prompt else None,
        triggered_at=run.triggered_at.isoformat() if run.triggered_at else None,
        status=run.status,
        session_id=run.session_id,
        collection_method=run.collection_method or "api",
        results=[
            ResultOut(
                id=r.id, llm=r.llm, raw_response=r.raw_response,
                mentioned=r.mentioned, position_score=r.position_score,
                sentiment=r.sentiment,
                competitors_mentioned=json.loads(r.competitors_mentioned or "[]"),
                error=r.error, latency_ms=r.latency_ms,
                prompt_tokens=r.prompt_tokens or 0,
                completion_tokens=r.completion_tokens or 0,
                total_tokens=r.total_tokens or 0,
                cost_usd=r.cost_usd or 0.0,
            )
            for r in run.results
        ],
    )
