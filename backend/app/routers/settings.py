from __future__ import annotations

import os
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.database import get_db
from app.models import AppSetting

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Keys stored in app_settings table
_SETTING_KEYS = [
    "target_company", "competitors",
    "openai_key", "gemini_key", "perplexity_key",
    "brightdata_key", "brightdata_zone",
]


def _get(db: Session, key: str) -> Optional[str]:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row else None


def _set(db: Session, key: str, value: str) -> None:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()
    # Keep running process in sync so adapters that read os.getenv still work
    os.environ[key.upper()] = value


def load_settings_into_env(db: Session) -> None:
    """Called on startup to populate os.environ from DB (DB overrides Secret Manager)."""
    for key in _SETTING_KEYS:
        val = _get(db, key)
        if val:
            os.environ[key.upper()] = val


class SettingsOut(BaseModel):
    target_company: str
    competitors: List[str]
    openai_key_set: bool
    gemini_key_set: bool
    perplexity_key_set: bool
    brightdata_key_set: bool
    brightdata_zone: str


class SettingsBody(BaseModel):
    target_company: str
    competitors: List[str]
    openai_key: Optional[str] = None
    gemini_key: Optional[str] = None
    perplexity_key: Optional[str] = None
    brightdata_key: Optional[str] = None
    brightdata_zone: Optional[str] = None


@router.get("/", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    target = _get(db, "target_company") or os.getenv("TARGET_COMPANY", "")
    competitors_raw = _get(db, "competitors") or os.getenv("COMPETITORS", "")
    competitors = [c.strip() for c in competitors_raw.split(",") if c.strip()]

    openai_key = _get(db, "openai_key") or os.getenv("OPENAI_API_KEY", "")
    gemini_key = _get(db, "gemini_key") or os.getenv("GEMINI_API_KEY", "")
    perplexity_key = _get(db, "perplexity_key") or os.getenv("PERPLEXITY_API_KEY", "")
    brightdata_key = _get(db, "brightdata_key") or os.getenv("BRIGHTDATA_API_KEY", "")
    brightdata_zone = _get(db, "brightdata_zone") or os.getenv("BRIGHTDATA_ZONE", "residential_proxy")

    return SettingsOut(
        target_company=target,
        competitors=competitors,
        openai_key_set=bool(openai_key),
        gemini_key_set=bool(gemini_key),
        perplexity_key_set=bool(perplexity_key),
        brightdata_key_set=bool(brightdata_key),
        brightdata_zone=brightdata_zone,
    )


@router.put("/", response_model=SettingsOut)
def update_settings(body: SettingsBody, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    _set(db, "target_company", body.target_company)
    _set(db, "competitors", ",".join(body.competitors))

    if body.openai_key is not None:
        _set(db, "openai_key", body.openai_key)
        os.environ["OPENAI_API_KEY"] = body.openai_key
    if body.gemini_key is not None:
        _set(db, "gemini_key", body.gemini_key)
        os.environ["GEMINI_API_KEY"] = body.gemini_key
    if body.perplexity_key is not None:
        _set(db, "perplexity_key", body.perplexity_key)
        os.environ["PERPLEXITY_API_KEY"] = body.perplexity_key
    if body.brightdata_key is not None:
        _set(db, "brightdata_key", body.brightdata_key)
        os.environ["BRIGHTDATA_API_KEY"] = body.brightdata_key
    if body.brightdata_zone is not None:
        _set(db, "brightdata_zone", body.brightdata_zone)
        os.environ["BRIGHTDATA_ZONE"] = body.brightdata_zone

    return get_settings(db)
