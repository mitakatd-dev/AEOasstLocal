"""
Authentication — local-only edition.

All requests are treated as admin. No Firebase, no tokens, no login required.
"""
from __future__ import annotations

LOCAL_USER = {"uid": "local", "role": "admin", "email": "local@localhost"}


def get_current_user() -> dict:
    return LOCAL_USER


def require_viewer() -> dict:
    return LOCAL_USER


def require_admin() -> dict:
    return LOCAL_USER
