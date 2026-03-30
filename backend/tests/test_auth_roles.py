"""
Tests for require_admin and require_viewer auth dependencies.

Strategy: override get_current_user in app.dependency_overrides to inject
different role payloads, then verify the correct HTTP status codes are returned
on protected endpoints.

Endpoints under test:
  - POST /api/prompts/          → require_admin
  - DELETE /api/prompts/{id}    → require_admin
  - GET /api/costs/summary      → open (no auth guard on costs router)
  - PUT /api/settings/          → require_admin
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_prompt


def _inject_role(app, role: str | None):
    """Override get_current_user to return a user with the given role."""
    from app.auth import get_current_user

    def _mock_user():
        return {"uid": "test-user", "email": "test@test.com", "role": role}

    app.dependency_overrides[get_current_user] = _mock_user
    return _mock_user


def _clear_overrides(app):
    from app.auth import get_current_user
    app.dependency_overrides.pop(get_current_user, None)


# ── require_admin tests ────────────────────────────────────────────────────────

class TestRequireAdmin:
    """
    require_admin must:
      - Allow role='admin'
      - Block role='viewer' with 403
      - Block role=None with 403
    """

    def test_admin_can_create_prompt(self, test_engine):
        from app.main import app
        _inject_role(app, "admin")
        try:
            with TestClient(app) as c:
                r = c.post("/api/prompts/", json={
                    "label": "Admin created",
                    "text": "Test text",
                    "query_type": "category",
                })
                assert r.status_code in (200, 201), r.text
        finally:
            _clear_overrides(app)

    def test_viewer_cannot_create_prompt(self, test_engine):
        from app.main import app
        _inject_role(app, "viewer")
        try:
            with TestClient(app) as c:
                r = c.post("/api/prompts/", json={
                    "label": "Viewer attempt",
                    "text": "Test text",
                    "query_type": "category",
                })
                assert r.status_code == 403, r.text
        finally:
            _clear_overrides(app)

    def test_no_role_cannot_create_prompt(self, test_engine):
        from app.main import app
        _inject_role(app, None)
        try:
            with TestClient(app) as c:
                r = c.post("/api/prompts/", json={
                    "label": "No role attempt",
                    "text": "Test text",
                    "query_type": "category",
                })
                assert r.status_code == 403, r.text
        finally:
            _clear_overrides(app)

    def test_admin_can_delete_prompt(self, test_engine, db):
        from app.main import app
        p = make_prompt(db, label="To delete by admin")
        _inject_role(app, "admin")
        try:
            with TestClient(app) as c:
                r = c.delete(f"/api/prompts/{p.id}")
                assert r.status_code in (200, 204), r.text
        finally:
            _clear_overrides(app)

    def test_viewer_cannot_delete_prompt(self, test_engine, db):
        from app.main import app
        p = make_prompt(db, label="Protected from viewer")
        _inject_role(app, "viewer")
        try:
            with TestClient(app) as c:
                r = c.delete(f"/api/prompts/{p.id}")
                assert r.status_code == 403, r.text
        finally:
            _clear_overrides(app)

    def test_admin_can_update_settings(self, test_engine):
        from app.main import app
        _inject_role(app, "admin")
        try:
            with TestClient(app) as c:
                r = c.put("/api/settings/", json={
                    "target_company": "TestCo",
                    "competitors": ["CompA", "CompB"],
                })
                assert r.status_code in (200, 201), r.text
        finally:
            _clear_overrides(app)

    def test_viewer_cannot_update_settings(self, test_engine):
        from app.main import app
        _inject_role(app, "viewer")
        try:
            with TestClient(app) as c:
                r = c.put("/api/settings/", json={
                    "target_company": "Blocked",
                    "competitors": [],
                })
                assert r.status_code == 403, r.text
        finally:
            _clear_overrides(app)


# ── require_viewer tests ───────────────────────────────────────────────────────

class TestRequireViewer:
    """
    require_viewer must:
      - Allow role='admin'
      - Allow role='viewer'
      - Block role=None with 403
    """

    def test_viewer_can_read_prompts(self, test_engine):
        from app.main import app
        _inject_role(app, "viewer")
        try:
            with TestClient(app) as c:
                r = c.get("/api/prompts/")
                assert r.status_code == 200, r.text
        finally:
            _clear_overrides(app)

    def test_admin_can_read_prompts(self, test_engine):
        from app.main import app
        _inject_role(app, "admin")
        try:
            with TestClient(app) as c:
                r = c.get("/api/prompts/")
                assert r.status_code == 200, r.text
        finally:
            _clear_overrides(app)
