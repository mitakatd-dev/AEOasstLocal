from __future__ import annotations

from typing import List, Optional
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models import Experiment, Prompt, Run, Result
from app.services.analyzer import compare_variants

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


class ExperimentCreate(BaseModel):
    name: str
    hypothesis: str
    variant_group: str


class ExperimentUpdate(BaseModel):
    status: Optional[str] = None
    conclusion: Optional[str] = None


class ExperimentOut(BaseModel):
    id: int
    name: str
    hypothesis: str
    variant_group: str
    status: str
    created_at: Optional[str] = None
    concluded_at: Optional[str] = None
    conclusion: Optional[str] = None

    class Config:
        from_attributes = True


def _exp_to_out(e: Experiment) -> ExperimentOut:
    return ExperimentOut(
        id=e.id,
        name=e.name,
        hypothesis=e.hypothesis,
        variant_group=e.variant_group,
        status=e.status,
        created_at=e.created_at.isoformat() if e.created_at else None,
        concluded_at=e.concluded_at.isoformat() if e.concluded_at else None,
        conclusion=e.conclusion,
    )


@router.get("/", response_model=List[ExperimentOut])
def list_experiments(db: Session = Depends(get_db)):
    exps = db.query(Experiment).order_by(Experiment.created_at.desc()).all()
    return [_exp_to_out(e) for e in exps]


@router.post("/", response_model=ExperimentOut, status_code=201)
def create_experiment(body: ExperimentCreate, db: Session = Depends(get_db)):
    exp = Experiment(
        name=body.name,
        hypothesis=body.hypothesis,
        variant_group=body.variant_group,
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)
    return _exp_to_out(exp)


@router.get("/{exp_id}")
def get_experiment(exp_id: int, db: Session = Depends(get_db)):
    exp = db.query(Experiment).filter(Experiment.id == exp_id).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")

    prompts = (
        db.query(Prompt)
        .filter(Prompt.variant_group == exp.variant_group)
        .all()
    )

    prompt_ids = [p.id for p in prompts]
    runs = (
        db.query(Run)
        .filter(Run.prompt_id.in_(prompt_ids))
        .order_by(Run.triggered_at.desc())
        .all()
    )

    return {
        **_exp_to_out(exp).dict(),
        "prompts": [
            {
                "id": p.id,
                "label": p.label,
                "text": p.text,
                "query_type": p.query_type,
                "variant_group": p.variant_group,
            }
            for p in prompts
        ],
        "runs": [
            {
                "id": r.id,
                "prompt_id": r.prompt_id,
                "triggered_at": r.triggered_at.isoformat() if r.triggered_at else None,
                "status": r.status,
            }
            for r in runs
        ],
    }


@router.put("/{exp_id}", response_model=ExperimentOut)
def update_experiment(exp_id: int, body: ExperimentUpdate, db: Session = Depends(get_db)):
    exp = db.query(Experiment).filter(Experiment.id == exp_id).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    if body.status is not None:
        exp.status = body.status
        if body.status == "concluded":
            exp.concluded_at = datetime.now(timezone.utc)
    if body.conclusion is not None:
        exp.conclusion = body.conclusion
    db.commit()
    db.refresh(exp)
    return _exp_to_out(exp)


@router.delete("/{exp_id}", status_code=204)
def delete_experiment(exp_id: int, db: Session = Depends(get_db)):
    exp = db.query(Experiment).filter(Experiment.id == exp_id).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    db.delete(exp)
    db.commit()


@router.get("/{exp_id}/comparison")
def get_comparison(exp_id: int, db: Session = Depends(get_db)):
    exp = db.query(Experiment).filter(Experiment.id == exp_id).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return compare_variants(exp.variant_group, db)
