from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from typing import Optional, List
import json
import uuid
import os

from app.database import get_db
from app.models import Prompt, Run, Result, BrowserWorker, WorkerBatch, WorkerScreenshot, Citation
from app.services.runner import _save_citations
from app.services.analyzer import analyze
from app.config import BROWSER_TO_LLM
from app import runner_manager
from app.auth import require_admin

router = APIRouter(prefix="/api/runner", tags=["runner"])


# ─── Request / Response models ──────────────────────────────────────────────

class RegisterRequest(BaseModel):
    worker_id: Optional[str] = None  # if resuming
    name: str
    platform: str
    account_hint: Optional[str] = None
    execution_name: Optional[str] = None  # Cloud Run Job execution resource name


class ClaimRequest(BaseModel):
    worker_id:  str
    platform:   str
    batch_size: Optional[int]       = 100
    # If provided, only claim from this specific set of prompt IDs
    prompt_ids: Optional[List[int]] = None
    # Session to attach all resulting Runs to
    session_id: Optional[str]       = None


class HeartbeatRequest(BaseModel):
    worker_id: str
    status: Optional[str] = "running"
    completed: Optional[int] = None
    batch_id: Optional[str] = None
    log_lines: Optional[list] = None  # new log lines since last heartbeat


class RunnerResultPayload(BaseModel):
    worker_id: str
    batch_id: str
    prompt_id: int
    platform: str
    raw_response: str
    citations: Optional[list] = []
    latency_ms: Optional[int] = 0
    error: Optional[str] = None


class BatchCompleteRequest(BaseModel):
    worker_id: str
    batch_id: str
    paused_s: Optional[int] = 0


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/register")
def register_worker(req: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new worker or re-register an existing one."""
    worker_id = req.worker_id or str(uuid.uuid4())

    worker = db.query(BrowserWorker).filter(BrowserWorker.id == worker_id).first()
    if worker:
        # Re-registration: update heartbeat and status
        worker.last_heartbeat = datetime.now(timezone.utc)
        worker.status = "idle"
    else:
        worker = BrowserWorker(
            id=worker_id,
            name=req.name,
            platform=req.platform,
            account_hint=req.account_hint,
            status="idle",
            last_heartbeat=datetime.now(timezone.utc),
        )
        db.add(worker)

    # Persist the Cloud Run execution name so stop works across service instances
    if req.execution_name:
        worker.execution_name = req.execution_name

    db.commit()
    return {"ok": True, "worker_id": worker_id}


@router.post("/claim")
def claim_batch(req: ClaimRequest, db: Session = Depends(get_db)):
    """
    Worker claims a batch of prompts to process.
    Returns prompts not yet completed by any worker for this platform.
    """
    worker = db.query(BrowserWorker).filter(BrowserWorker.id == req.worker_id).first()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not registered")

    # Find prompt IDs already being processed by ACTIVE batches for this platform.
    # Completed batches are intentionally excluded — prompts should be re-runnable
    # in new research sessions once a previous session has finished.
    existing_batches = db.query(WorkerBatch).filter(
        WorkerBatch.platform == req.platform,
        WorkerBatch.status.in_(["claimed", "running"]),
    ).all()

    claimed_prompt_ids = set()
    for batch in existing_batches:
        claimed_prompt_ids.update(json.loads(batch.prompt_ids))

    # Get prompts — if caller specified a subset, restrict to those IDs
    q = db.query(Prompt).order_by(Prompt.id)
    if req.prompt_ids:
        q = q.filter(Prompt.id.in_(req.prompt_ids))
    all_prompts = q.all()
    unclaimed = [p for p in all_prompts if p.id not in claimed_prompt_ids]

    if not unclaimed:
        return {"ok": True, "batch_id": None, "prompts": [], "message": "All prompts already claimed"}

    # Take up to batch_size prompts
    to_claim = unclaimed[:req.batch_size]
    prompt_ids = [p.id for p in to_claim]

    # Create the batch
    batch_id = str(uuid.uuid4())[:8]
    batch = WorkerBatch(
        id=batch_id,
        worker_id=req.worker_id,
        platform=req.platform,
        prompt_ids=json.dumps(prompt_ids),
        session_id=req.session_id,
        total=len(prompt_ids),
        completed=0,
        failed=0,
        status="claimed",
    )
    db.add(batch)

    # Update worker status
    worker.status = "running"
    worker.last_heartbeat = datetime.now(timezone.utc)
    db.commit()

    prompts_data = [
        {
            "id": p.id,
            "label": p.label,
            "text": p.text,
            "query_type": p.query_type,
            "target_llm": req.platform,
        }
        for p in to_claim
    ]

    return {
        "ok": True,
        "batch_id": batch_id,
        "total": len(prompt_ids),
        "prompts": prompts_data,
    }


@router.post("/result")
def submit_result(payload: RunnerResultPayload, db: Session = Depends(get_db)):
    """Worker submits a single result."""
    target = os.getenv("TARGET_COMPANY", "")
    competitors_str = os.getenv("COMPETITORS", "")
    competitor_list = [c.strip() for c in competitors_str.split(",") if c.strip()]

    internal_llm = BROWSER_TO_LLM.get(payload.platform, payload.platform)

    # Resolve session_id from the batch
    batch_for_session = db.query(WorkerBatch).filter(WorkerBatch.id == payload.batch_id).first()
    session_id = batch_for_session.session_id if batch_for_session else None

    # Create Run + Result
    run = Run(
        prompt_id=payload.prompt_id,
        triggered_at=datetime.now(timezone.utc),
        status="completed" if not payload.error else "failed",
        session_id=session_id,
        collection_method="browser",
    )
    db.add(run)
    db.flush()

    if payload.raw_response and not payload.error:
        analysis = analyze(payload.raw_response, target, competitor_list)
    else:
        analysis = {
            "mentioned": False,
            "position_score": None,
            "sentiment": "neutral",
            "competitors_mentioned": [],
        }

    result = Result(
        run_id=run.id,
        llm=internal_llm,
        raw_response=payload.raw_response or "",
        mentioned=analysis["mentioned"],
        position_score=analysis["position_score"],
        sentiment=analysis["sentiment"],
        competitors_mentioned=json.dumps(analysis["competitors_mentioned"]),
        error=payload.error,
        latency_ms=payload.latency_ms or 0,
    )
    db.add(result)
    db.flush()

    # Save structured citations to Citation table (browser collection)
    if payload.citations and not payload.error:
        _save_citations(db, result.id, payload.citations, method="browser")

    # Update batch progress
    batch = db.query(WorkerBatch).filter(WorkerBatch.id == payload.batch_id).first()
    if batch:
        if payload.error:
            batch.failed += 1
        else:
            batch.completed += 1
        batch.status = "running"

    db.commit()

    return {
        "ok": True,
        "run_id": run.id,
        "mentioned": analysis["mentioned"],
        "sentiment": analysis["sentiment"],
    }


@router.post("/heartbeat")
def heartbeat(req: HeartbeatRequest, db: Session = Depends(get_db)):
    """Worker sends alive signal.

    If the worker has been stopped via /api/runner/stop, rejects the heartbeat
    and returns stop=True so the runner process exits gracefully rather than
    continuing to run and then overwriting the 'stopped' status on the next beat.
    """
    worker = db.query(BrowserWorker).filter(BrowserWorker.id == req.worker_id).first()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")

    # Guard: terminal workers must not be resurrected by a late heartbeat.
    # "stopped" — user clicked Stop; "done" — batch completed normally.
    # In both cases the Cloud Run Job may still be shutting down and can
    # send one final heartbeat. Without this guard that heartbeat would flip
    # the terminal status back to "running", breaking the UI on next refresh.
    if worker.status in ("stopped", "done"):
        return {"ok": False, "stop": True}

    worker.last_heartbeat = datetime.now(timezone.utc)
    if req.status:
        worker.status = req.status

    if req.batch_id and req.completed is not None:
        batch = db.query(WorkerBatch).filter(WorkerBatch.id == req.batch_id).first()
        if batch:
            batch.completed = req.completed

    # Append new log lines (cloud mode: runner sends lines via heartbeat)
    if req.log_lines:
        existing = worker.log_lines or ""
        new_lines = "\n".join(str(l) for l in req.log_lines)
        worker.log_lines = (existing + "\n" + new_lines).strip()

    db.commit()
    return {"ok": True}


@router.post("/complete")
def complete_batch(req: BatchCompleteRequest, db: Session = Depends(get_db)):
    """Worker marks batch as complete."""
    batch = db.query(WorkerBatch).filter(WorkerBatch.id == req.batch_id).first()
    if batch:
        batch.status = "completed"
        batch.completed_at = datetime.now(timezone.utc)
        batch.total_paused_s = req.paused_s or 0

    worker = db.query(BrowserWorker).filter(BrowserWorker.id == req.worker_id).first()
    if worker:
        worker.status = "done"

    db.commit()
    return {"ok": True}


@router.get("/status")
def runner_status(db: Session = Depends(get_db)):
    """Returns full runner status for the dashboard."""
    all_workers = db.query(BrowserWorker).order_by(BrowserWorker.registered_at.desc()).all()
    now = datetime.now(timezone.utc)

    # Keep only the most recent registration per worker name (avoid stale duplicates)
    seen_names: set = set()
    deduped = []
    for w in all_workers:
        if w.name not in seen_names:
            seen_names.add(w.name)
            deduped.append(w)
    workers = deduped

    result = []
    for w in workers:
        batches = db.query(WorkerBatch).filter(WorkerBatch.worker_id == w.id).all()

        total_prompts   = sum(b.total     for b in batches)
        total_completed = sum(b.completed for b in batches)
        total_failed    = sum(b.failed    for b in batches)

        # Stale if no heartbeat for > 5 minutes
        is_stale = False
        if w.last_heartbeat:
            hb_ts = w.last_heartbeat.replace(tzinfo=timezone.utc) if w.last_heartbeat.tzinfo is None else w.last_heartbeat
            is_stale = (now - hb_ts) > timedelta(minutes=5)

        # Check flag files — authoritative sources for gate states
        needs_login_flag = runner_manager.needs_login(w.platform, w.name)
        is_paused_flag   = runner_manager.is_paused(w.platform, w.name)

        # Derive display status: flag files win over DB status.
        # If stale and still in an active DB status, auto-reconcile:
        # mark the worker stopped and fail its pending runs so the batch
        # resolves correctly without any manual intervention.
        if needs_login_flag:
            display_status = "waiting_login"
        elif is_paused_flag:
            display_status = "paused"
        elif is_stale and w.status in ("running", "waiting_login", "paused"):
            # Auto-cleanup: transition from stale active state → stopped in DB.
            # The next poll will see w.status="stopped" and fall through to the
            # branch below, which promotes it to "done" so the UI clears it.
            w.status = "stopped"
            session_ids = {
                b.session_id for b in batches
                if b.session_id and b.status not in ("completed", "error")
            }
            for b in batches:
                if b.status not in ("completed", "error"):
                    b.status = "error"
            if session_ids:
                db.query(Run).filter(
                    Run.session_id.in_(list(session_ids)),
                    Run.status == "running",
                ).update({"status": "failed"}, synchronize_session=False)
            db.commit()
            display_status = "stopped"
        elif is_stale and w.status == "stopped":
            # Second pass: stale + already stopped → promote to "done" so the UI
            # removes it from the active workers list. Without this, "stopped"
            # workers stay visible forever (the UI treats stopped as active).
            w.status = "done"
            db.commit()
            display_status = "done"
        else:
            display_status = w.status

        result.append({
            "worker_id":      w.id,
            "name":           w.name,
            "platform":       w.platform,
            "account_hint":   w.account_hint,
            "status":         display_status,
            "needs_login":    needs_login_flag,
            "is_paused":      is_paused_flag,
            "last_heartbeat": w.last_heartbeat.isoformat() if w.last_heartbeat else None,
            "registered_at":  w.registered_at.isoformat() if w.registered_at else None,
            "total_prompts":  total_prompts,
            "completed":      total_completed,
            "failed":         total_failed,
            "progress_pct":   round(total_completed / total_prompts * 100, 1) if total_prompts > 0 else 0,
            "batches": [
                {
                    "batch_id":     b.id,
                    "status":       b.status,
                    "total":        b.total,
                    "completed":    b.completed,
                    "failed":       b.failed,
                    "claimed_at":   b.claimed_at.isoformat()   if b.claimed_at   else None,
                    "completed_at": b.completed_at.isoformat() if b.completed_at else None,
                }
                for b in batches
            ],
        })

    # Summary
    all_batches = db.query(WorkerBatch).all()
    total_prompts_all   = sum(b.total     for b in all_batches)
    total_completed_all = sum(b.completed for b in all_batches)

    return {
        "workers": result,
        "summary": {
            "total_workers":   len(workers),
            "active_workers":  sum(1 for w in workers if w.status == "running"),
            "done_workers":    sum(1 for w in workers if w.status == "done"),
            "total_prompts":   total_prompts_all,
            "total_completed": total_completed_all,
            "overall_pct":     round(total_completed_all / total_prompts_all * 100, 1) if total_prompts_all > 0 else 0,
        }
    }


@router.delete("/workers")
def reset_workers(db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    """Reset all workers and batches (for fresh run).
    Also fails any runs still marked 'running' that belong to worker sessions,
    so the batch history shows correct final state rather than staying active forever.
    """
    all_batches = db.query(WorkerBatch).all()
    session_ids = {b.session_id for b in all_batches if b.session_id}
    if session_ids:
        db.query(Run).filter(
            Run.session_id.in_(list(session_ids)),
            Run.status == "running",
        ).update({"status": "failed"}, synchronize_session=False)
    db.query(WorkerBatch).delete()
    db.query(BrowserWorker).delete()
    db.commit()
    return {"ok": True}


# ─── Process management ───────────────────────────────────────────────────────

class LaunchRequest(BaseModel):
    platform:   str
    name:       Optional[str]       = None
    batch_size: Optional[int]       = 100
    prompt_ids: Optional[List[int]] = None
    session_id: Optional[str]       = None


class LoginReadyRequest(BaseModel):
    platform: str
    name:     str


class StopRequest(BaseModel):
    name: str


class PauseRequest(BaseModel):
    name:     str
    platform: str


@router.post("/launch")
def launch_runner(req: LaunchRequest, _: dict = Depends(require_admin)):
    """Spawn a Playwright runner subprocess for the given platform."""
    name = req.name or f"{req.platform}-1"
    try:
        pid = runner_manager.launch(
            req.platform, name, req.batch_size or 100,
            prompt_ids=req.prompt_ids,
            session_id=req.session_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True, "name": name, "pid": pid}


@router.post("/stop")
def stop_runner(req: StopRequest, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    """Terminate a running worker subprocess and mark all its in-progress runs as failed."""
    runner_manager.stop(req.name)

    # Persist the stop: mark the worker and any still-running runs as stopped/failed
    # so the UI correctly shows the batch as finished after a page refresh.
    workers = db.query(BrowserWorker).filter(BrowserWorker.name == req.name).all()
    session_ids = set()
    for worker in workers:
        worker.status = "stopped"
        for batch in worker.batches:
            if batch.status not in ("completed", "error"):
                batch.status = "error"
            if batch.session_id:
                session_ids.add(batch.session_id)

    if session_ids:
        db.query(Run).filter(
            Run.session_id.in_(list(session_ids)),
            Run.status == "running",
        ).update({"status": "failed"}, synchronize_session=False)

    db.commit()
    return {"ok": True}


@router.post("/pause")
def pause_runner(req: PauseRequest, _: dict = Depends(require_admin)):
    """Pause a running worker after its current prompt completes."""
    runner_manager.pause(req.platform, req.name)
    return {"ok": True}


@router.post("/resume")
def resume_runner(req: PauseRequest, _: dict = Depends(require_admin)):
    """Resume a paused worker."""
    runner_manager.resume(req.platform, req.name)
    return {"ok": True}


@router.post("/login-ready")
def login_ready(req: LoginReadyRequest, _: dict = Depends(require_admin)):
    """Signal that the user has logged in — unblocks the runner."""
    runner_manager.signal_login_ready(req.platform, req.name)
    return {"ok": True}


@router.get("/logs/{name}")
def get_logs(name: str, platform: str, lines: int = 80):
    """Return last N lines of a runner's log file plus parsed live progress."""
    return {
        "name":     name,
        "lines":    runner_manager.get_logs(platform, name, lines),
        "progress": runner_manager.parse_log_progress(platform, name),
    }


@router.get("/alive/{name}")
def check_alive(name: str):
    """Check if a subprocess is still running."""
    platform = name.split("-")[0] if "-" in name else name
    return {
        "alive":       runner_manager.is_alive(name),
        "pid":         runner_manager.pid_of(name),
        "needs_login": runner_manager.needs_login(platform, name),
        "is_paused":   runner_manager.is_paused(platform, name),
    }


# ── Screenshot endpoints ──────────────────────────────────────────────────────

class ScreenshotUpload(BaseModel):
    worker_id: str
    name:      str
    data:      str   # base64 JPEG
    label:     str = ""


@router.post("/screenshot")
def upload_screenshot(req: ScreenshotUpload, db: Session = Depends(get_db)):
    """Runner posts a screenshot; upserted in DB keyed by worker name."""
    row = db.query(WorkerScreenshot).filter(WorkerScreenshot.worker_name == req.name).first()
    now = datetime.now(timezone.utc)
    if row:
        row.data = req.data
        row.label = req.label
        row.captured_at = now
    else:
        row = WorkerScreenshot(worker_name=req.name, data=req.data, label=req.label, captured_at=now)
        db.add(row)
    db.commit()
    return {"ok": True}


@router.get("/screenshot/{name}")
def get_screenshot(name: str, db: Session = Depends(get_db)):
    """Return the latest screenshot for a worker (base64 JPEG + label + timestamp)."""
    row = db.query(WorkerScreenshot).filter(WorkerScreenshot.worker_name == name).first()
    if not row or not row.data:
        return {"data": None, "label": None, "timestamp": None}
    return {
        "data":      row.data,
        "label":     row.label,
        "timestamp": row.captured_at.isoformat() if row.captured_at else None,
    }
