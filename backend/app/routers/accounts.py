"""
Browser account pool management.

Stores Playwright storage_state (cookies + localStorage) per platform account.
Multiple accounts per platform — round-robin rotation via last_used_at (LRU).

Endpoints:
  GET  /api/accounts/          — list all accounts (admin only, no storage_state returned)
  POST /api/accounts/          — add account with storage_state JSON (admin only)
  PUT  /api/accounts/{id}/expire — mark account as expired (admin only)
  DELETE /api/accounts/{id}    — remove account (admin only)
  GET  /api/accounts/claim     — runner: claim LRU active session for a platform (open)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models import BrowserAccount

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

PLATFORMS = ("chatgpt", "gemini", "perplexity")


# ── Schemas ───────────────────────────────────────────────────────────────────

class AccountInfo(BaseModel):
    id: str
    platform: str
    label: str
    status: str
    has_session: bool
    last_used_at: Optional[str] = None
    created_at: Optional[str] = None


class AccountCreate(BaseModel):
    platform: str
    label: str
    storage_state: str   # JSON string produced by capture_session.py


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_info(a: BrowserAccount) -> AccountInfo:
    return AccountInfo(
        id=a.id,
        platform=a.platform,
        label=a.label,
        status=a.status,
        has_session=bool(a.storage_state),
        last_used_at=a.last_used_at.isoformat() if a.last_used_at else None,
        created_at=a.created_at.isoformat() if a.created_at else None,
    )


# ── CRUD endpoints (admin only) ───────────────────────────────────────────────

@router.get("/", response_model=List[AccountInfo])
def list_accounts(
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> List[AccountInfo]:
    """List all browser accounts (no storage_state exposed)."""
    rows = db.query(BrowserAccount).order_by(BrowserAccount.platform, BrowserAccount.created_at).all()
    return [_to_info(a) for a in rows]


@router.post("/", response_model=AccountInfo)
def create_account(
    body: AccountCreate,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AccountInfo:
    """Upload a captured session. storage_state must be valid JSON."""
    if body.platform not in PLATFORMS:
        raise HTTPException(400, f"platform must be one of {PLATFORMS}")
    try:
        json.loads(body.storage_state)
    except Exception:
        raise HTTPException(400, "storage_state must be valid JSON")

    account = BrowserAccount(
        id=str(uuid.uuid4()),
        platform=body.platform,
        label=body.label,
        storage_state=body.storage_state,
        status="active",
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return _to_info(account)


@router.put("/{account_id}/expire")
def expire_account(
    account_id: str,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Mark an account session as expired (keeps the record for re-upload)."""
    account = db.query(BrowserAccount).filter(BrowserAccount.id == account_id).first()
    if not account:
        raise HTTPException(404, "Account not found")
    account.status = "expired"
    db.commit()
    return {"ok": True, "id": account_id}


@router.delete("/{account_id}")
def delete_account(
    account_id: str,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Remove an account record entirely."""
    account = db.query(BrowserAccount).filter(BrowserAccount.id == account_id).first()
    if not account:
        raise HTTPException(404, "Account not found")
    db.delete(account)
    db.commit()
    return {"ok": True}


# ── Runner claim endpoint (open — consistent with other runner endpoints) ─────

@router.get("/claim")
def claim_session(
    platform: str,
    db: Session = Depends(get_db),
) -> dict:
    """
    Internal endpoint for runners: fetch the least-recently-used active session
    for the given platform.  Stamps last_used_at so the next claim picks a
    different account (round-robin rotation).

    Returns:
      { found: bool, account_id: str|null, storage_state: str|null }
    """
    account = (
        db.query(BrowserAccount)
        .filter(
            BrowserAccount.platform == platform,
            BrowserAccount.status == "active",
        )
        .order_by(BrowserAccount.last_used_at.asc().nullsfirst())
        .first()
    )

    if not account:
        return {"found": False, "account_id": None, "storage_state": None}

    account.last_used_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "found": True,
        "account_id": account.id,
        "storage_state": account.storage_state,
    }
