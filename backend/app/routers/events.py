from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional

from app.database import get_db
from app.models import ExternalEvent

router = APIRouter(prefix="/api/events", tags=["events"])


class EventCreate(BaseModel):
    date: str
    description: str


@router.get("/")
def list_events(db: Session = Depends(get_db)):
    events = db.query(ExternalEvent).order_by(ExternalEvent.date.desc()).all()
    return [
        {
            "id": e.id,
            "date": e.date.isoformat() if e.date else None,
            "description": e.description,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]


@router.post("/")
def create_event(body: EventCreate, db: Session = Depends(get_db)):
    event = ExternalEvent(
        date=datetime.fromisoformat(body.date),
        description=body.description,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return {
        "id": event.id,
        "date": event.date.isoformat() if event.date else None,
        "description": event.description,
    }


@router.delete("/{event_id}")
def delete_event(event_id: int, db: Session = Depends(get_db)):
    event = db.query(ExternalEvent).get(event_id)
    if not event:
        return {"error": "Not found"}
    db.delete(event)
    db.commit()
    return {"ok": True}


@router.get("/range")
def events_in_range(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(ExternalEvent)
    if start:
        q = q.filter(ExternalEvent.date >= datetime.fromisoformat(start))
    if end:
        q = q.filter(ExternalEvent.date <= datetime.fromisoformat(end))
    events = q.order_by(ExternalEvent.date).all()
    return [
        {
            "id": e.id,
            "date": e.date.isoformat() if e.date else None,
            "description": e.description,
        }
        for e in events
    ]
