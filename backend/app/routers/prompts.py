from __future__ import annotations

import csv
import io
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session
from pydantic import BaseModel, validator

from app.database import get_db
from app.models import Prompt, Run, Result
from app.auth import require_admin

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

VALID_QUERY_TYPES = {"category", "problem", "comparison", "brand_direct"}


class PromptCreate(BaseModel):
    label: str
    text: str
    variant_group: Optional[str] = None
    query_type: Optional[str] = None

    @validator("query_type")
    def validate_query_type(cls, v):
        if v is not None and v not in VALID_QUERY_TYPES:
            raise ValueError(f"query_type must be one of: {', '.join(VALID_QUERY_TYPES)}")
        return v


class PromptOut(BaseModel):
    id: int
    label: str
    text: str
    variant_group: Optional[str] = None
    query_type: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


def _prompt_to_out(p: Prompt) -> PromptOut:
    return PromptOut(
        id=p.id,
        label=p.label,
        text=p.text,
        variant_group=p.variant_group,
        query_type=p.query_type,
        created_at=p.created_at.isoformat() if p.created_at else None,
    )


@router.get("/", response_model=List[PromptOut])
def list_prompts(
    query_type:    Optional[str] = Query(None),
    variant_group: Optional[str] = Query(None),
    date_from:     Optional[str] = Query(None),  # YYYY-MM-DD
    date_to:       Optional[str] = Query(None),  # YYYY-MM-DD
    db: Session = Depends(get_db),
):
    q = db.query(Prompt)
    if query_type:
        q = q.filter(Prompt.query_type == query_type)
    if variant_group:
        q = q.filter(Prompt.variant_group == variant_group)
    if date_from:
        try:
            dt = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            q = q.filter(Prompt.created_at >= dt)
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            q = q.filter(Prompt.created_at < dt)
        except ValueError:
            pass
    prompts = q.order_by(Prompt.created_at.desc()).all()
    return [_prompt_to_out(p) for p in prompts]


@router.post("/", response_model=PromptOut, status_code=201)
def create_prompt(body: PromptCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    prompt = Prompt(
        label=body.label,
        text=body.text,
        variant_group=body.variant_group,
        query_type=body.query_type,
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return _prompt_to_out(prompt)


@router.put("/{prompt_id}", response_model=PromptOut)
def update_prompt(prompt_id: int, body: PromptCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    prompt.label = body.label
    prompt.text = body.text
    prompt.variant_group = body.variant_group
    prompt.query_type = body.query_type
    db.commit()
    db.refresh(prompt)
    return _prompt_to_out(prompt)


class BulkReplaceRequest(BaseModel):
    find:    str
    replace: str


@router.post("/bulk-replace")
def bulk_replace(body: BulkReplaceRequest, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    """Find-and-replace a string across all prompt labels and texts."""
    if not body.find:
        raise HTTPException(status_code=400, detail="find cannot be empty")
    prompts = db.query(Prompt).all()
    updated = 0
    for p in prompts:
        new_text  = p.text.replace(body.find, body.replace)
        new_label = p.label.replace(body.find, body.replace)
        if new_text != p.text or new_label != p.label:
            p.text  = new_text
            p.label = new_label
            updated += 1
    db.commit()
    return {"updated": updated}


@router.post("/upload-csv", status_code=201)
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    """
    Bulk-create prompts from a CSV file.
    Required columns: label, text
    Optional columns: query_type, variant_group
    First row must be a header row.
    """
    content = await file.read()
    try:
        text_content = content.decode("utf-8-sig")  # handles BOM from Excel exports
    except UnicodeDecodeError:
        text_content = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text_content))
    if not reader.fieldnames or "label" not in reader.fieldnames or "text" not in reader.fieldnames:
        raise HTTPException(
            status_code=400,
            detail="CSV must have 'label' and 'text' columns. Optional: query_type, variant_group"
        )

    created = 0
    skipped = 0
    for row in reader:
        label = (row.get("label") or "").strip()
        text  = (row.get("text")  or "").strip()
        if not label or not text:
            skipped += 1
            continue
        query_type    = (row.get("query_type")    or "").strip() or None
        variant_group = (row.get("variant_group") or "").strip() or None
        if query_type and query_type not in VALID_QUERY_TYPES:
            query_type = None
        db.add(Prompt(label=label, text=text, query_type=query_type, variant_group=variant_group))
        created += 1

    db.commit()
    return {"created": created, "skipped": skipped}


@router.delete("/{prompt_id}", status_code=204)
def delete_prompt(prompt_id: int, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    # Delete related runs and results first (cascade)
    runs = db.query(Run).filter(Run.prompt_id == prompt_id).all()
    for run in runs:
        db.query(Result).filter(Result.run_id == run.id).delete()
        db.delete(run)
    db.delete(prompt)
    db.commit()
