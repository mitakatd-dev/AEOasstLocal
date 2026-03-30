from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import List, Optional
import json
import os
import io
import zipfile
import uuid

from app.database import get_db
from app.models import Prompt, Run, Result
from app.services.analyzer import analyze
from app.config import BROWSER_TO_LLM

router = APIRouter(prefix="/api/extension", tags=["extension"])

# In-memory batch tracking (lightweight, no extra DB table needed)
_batches = {}


class ResultPayload(BaseModel):
    batch_id: Optional[str] = None
    prompt_id: int
    llm: str  # 'chatgpt', 'gemini', 'perplexity'
    raw_response: str
    citations: Optional[list] = []
    latency_ms: Optional[int] = 0
    source: Optional[str] = "web_portal"
    error: Optional[str] = None


class BatchComplete(BaseModel):
    batch_id: Optional[str] = None


@router.get("/queue")
def get_queue(
    llm: Optional[str] = None,
    llms: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Returns the prompt queue for the extension.
    Filter by single llm param or comma-separated llms param.
    """
    prompts = db.query(Prompt).order_by(Prompt.id).all()

    if llms:
        target_llms = [l.strip() for l in llms.split(",") if l.strip()]
    elif llm:
        target_llms = [llm]
    else:
        # Default to chatgpt only — user must explicitly opt in to others
        target_llms = ["chatgpt"]

    queue = []
    for p in prompts:
        for target in target_llms:
            queue.append({
                "id": p.id,
                "label": p.label,
                "text": p.text,
                "query_type": p.query_type,
                "target_llm": target,
            })

    batch_id = str(uuid.uuid4())[:8]
    _batches[batch_id] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total": len(queue),
        "completed": 0,
        "status": "running",
    }

    return {
        "batch_id": batch_id,
        "total": len(queue),
        "prompts": queue,
    }


@router.post("/result")
def submit_result(
    payload: ResultPayload,
    db: Session = Depends(get_db),
):
    """
    Receives a single result from the Chrome extension.
    Creates a Run + Result, runs the analyzer, stores everything.
    """
    target = os.getenv("TARGET_COMPANY", "")
    competitors_str = os.getenv("COMPETITORS", "")
    competitor_list = [c.strip() for c in competitors_str.split(",") if c.strip()]

    internal_llm = BROWSER_TO_LLM.get(payload.llm, payload.llm)

    # Create a run for this prompt
    run = Run(
        prompt_id=payload.prompt_id,
        triggered_at=datetime.now(timezone.utc),
        status="completed" if not payload.error else "failed",
    )
    db.add(run)
    db.flush()

    # Analyze the response
    if payload.raw_response and not payload.error:
        analysis = analyze(payload.raw_response, target, competitor_list)
    else:
        analysis = {
            "mentioned": False,
            "position_score": None,
            "sentiment": "neutral",
            "competitors_mentioned": [],
        }

    # Store citations as JSON in the raw response (append)
    citations_text = ""
    if payload.citations:
        citations_text = "\n\n---CITATIONS---\n" + json.dumps(payload.citations)

    result = Result(
        run_id=run.id,
        llm=internal_llm,
        raw_response=(payload.raw_response or "") + citations_text,
        mentioned=analysis["mentioned"],
        position_score=analysis["position_score"],
        sentiment=analysis["sentiment"],
        competitors_mentioned=json.dumps(analysis["competitors_mentioned"]),
        error=payload.error,
        latency_ms=payload.latency_ms or 0,
    )
    db.add(result)
    db.commit()

    # Update batch counter
    if payload.batch_id and payload.batch_id in _batches:
        _batches[payload.batch_id]["completed"] += 1

    return {
        "ok": True,
        "run_id": run.id,
        "mentioned": analysis["mentioned"],
        "sentiment": analysis["sentiment"],
        "source": "web_portal",
    }


@router.post("/complete")
def batch_complete(payload: BatchComplete):
    """Mark a batch as complete."""
    if payload.batch_id and payload.batch_id in _batches:
        _batches[payload.batch_id]["status"] = "completed"
    return {"ok": True}


@router.get("/batches")
def list_batches():
    """List all extension batches."""
    return [
        {"batch_id": k, **v}
        for k, v in sorted(_batches.items(), key=lambda x: x[1]["created_at"], reverse=True)
    ]


@router.get("/download")
def download_extension():
    """
    Package the Chrome extension as a ZIP for download.
    The extension folder lives alongside the backend.
    """
    ext_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "..", "extension")
    ext_dir = os.path.abspath(ext_dir)

    if not os.path.isdir(ext_dir):
        return {"error": "Extension directory not found"}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ext_dir):
            for f in files:
                filepath = os.path.join(root, f)
                arcname = os.path.join("aeo-insights-extension", os.path.relpath(filepath, ext_dir))
                zf.write(filepath, arcname)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=aeo-insights-extension.zip"},
    )


@router.get("/status")
def extension_status():
    """Check if extension is reachable (used by the Collector page to verify connection)."""
    return {
        "ok": True,
        "version": "1.0.0",
        "endpoints": {
            "queue": "/api/extension/queue",
            "result": "/api/extension/result",
            "download": "/api/extension/download",
        },
    }
