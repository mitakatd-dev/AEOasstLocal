from __future__ import annotations

import os
import json
import asyncio
from urllib.parse import urlparse
from typing import List, Optional
from sqlalchemy.orm import Session

from app.models import Run, Result, Citation
from app.adapters import openai_adapter, gemini_adapter, perplexity_adapter
from app.services.analyzer import analyze


ALL_ADAPTERS = {
    "openai":      openai_adapter,
    "gemini":      gemini_adapter,
    "perplexity":  perplexity_adapter,
}


def _save_citations(db: Session, result_id: int, citations: list, method: str = "api") -> None:
    """Persist structured citation records linked to a Result row."""
    for c in (citations or []):
        url = c.get("url", "")
        if not url:
            continue
        try:
            domain = urlparse(url).netloc or ""
        except Exception:
            domain = ""
        db.add(Citation(
            result_id=result_id,
            url=url,
            title=c.get("title", "") or "",
            domain=domain,
            position=c.get("position", 0),
            collection_method=method,
        ))


async def execute_run(
    run_id: int,
    prompt_text: str,
    db: Session,
    platforms: Optional[List[str]] = None,
):
    """
    Call one or more LLM adapters for a single prompt and store results + citations.
    platforms: list of adapter keys. Defaults to all three if None.
    """
    target_company  = os.getenv("TARGET_COMPANY", "")
    competitors_str = os.getenv("COMPETITORS", "")
    competitors     = [c.strip() for c in competitors_str.split(",") if c.strip()]

    selected = {
        k: v for k, v in ALL_ADAPTERS.items()
        if platforms is None or k in platforms
    }

    tasks   = {name: adapter.call(prompt_text) for name, adapter in selected.items()}
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    error_count = 0
    for name, result in zip(tasks.keys(), results):
        if isinstance(result, Exception):
            result = {
                "response": None, "citations": [], "latency_ms": 0, "error": str(result),
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0,
            }

        raw_response = result.get("response")
        error        = result.get("error")
        citations    = result.get("citations") or []
        if error:
            error_count += 1

        analysis = analyze(raw_response or "", target_company, competitors)

        result_row = Result(
            run_id=run_id,
            llm=name,
            raw_response=raw_response,
            mentioned=analysis["mentioned"],
            position_score=analysis["position_score"],
            sentiment=analysis["sentiment"],
            competitors_mentioned=json.dumps(analysis["competitors_mentioned"]),
            error=error,
            latency_ms=result.get("latency_ms", 0),
            prompt_tokens=result.get("prompt_tokens", 0),
            completion_tokens=result.get("completion_tokens", 0),
            total_tokens=result.get("total_tokens", 0),
            cost_usd=result.get("cost_usd", 0.0),
        )
        db.add(result_row)
        db.flush()  # get result_row.id before saving citations

        if citations:
            _save_citations(db, result_row.id, citations, method="api")

    run = db.query(Run).filter(Run.id == run_id).first()
    if error_count == len(selected):
        run.status = "failed"
    elif error_count > 0:
        run.status = "partial"
    else:
        run.status = "completed"

    db.commit()
