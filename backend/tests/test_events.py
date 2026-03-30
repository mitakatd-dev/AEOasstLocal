"""
Tests for /api/events/* endpoints.

Covers:
- GET  /api/events/          — list all events
- POST /api/events/          — create event
- DELETE /api/events/{id}    — delete event
- GET  /api/events/range     — filter by date range
"""
from __future__ import annotations

import pytest


class TestListEvents:

    def test_returns_list(self, client):
        resp = client.get("/api/events/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_created_event_appears_in_list(self, client):
        client.post("/api/events/", json={"date": "2026-01-15", "description": "Test campaign"})

        resp = client.get("/api/events/")
        assert resp.status_code == 200
        descriptions = [e["description"] for e in resp.json()]
        assert "Test campaign" in descriptions


class TestCreateEvent:

    def test_creates_event_with_correct_fields(self, client):
        resp = client.post("/api/events/", json={"date": "2026-02-01", "description": "Blog post published"})
        assert resp.status_code == 200
        body = resp.json()
        assert "id" in body
        assert body["description"] == "Blog post published"
        assert "2026-02-01" in body["date"]

    def test_created_event_has_id(self, client):
        resp = client.post("/api/events/", json={"date": "2026-03-10", "description": "PR coverage"})
        assert isinstance(resp.json()["id"], int)

    def test_missing_description_returns_error(self, client):
        resp = client.post("/api/events/", json={"date": "2026-01-01"})
        assert resp.status_code == 422


class TestDeleteEvent:

    def test_deletes_event(self, client):
        create_resp = client.post("/api/events/", json={"date": "2026-04-01", "description": "To be deleted"})
        event_id = create_resp.json()["id"]

        del_resp = client.delete(f"/api/events/{event_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["ok"] is True

    def test_deleted_event_not_in_list(self, client):
        create_resp = client.post("/api/events/", json={"date": "2026-04-02", "description": "Ephemeral event"})
        event_id = create_resp.json()["id"]
        client.delete(f"/api/events/{event_id}")

        descriptions = [e["description"] for e in client.get("/api/events/").json()]
        assert "Ephemeral event" not in descriptions

    def test_delete_nonexistent_returns_error(self, client):
        resp = client.delete("/api/events/999999")
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestEventsRange:

    def test_range_returns_matching_events(self, client):
        client.post("/api/events/", json={"date": "2026-05-10", "description": "May event"})
        client.post("/api/events/", json={"date": "2026-07-20", "description": "July event"})

        resp = client.get("/api/events/range?start=2026-05-01&end=2026-05-31")
        assert resp.status_code == 200
        descriptions = [e["description"] for e in resp.json()]
        assert "May event" in descriptions
        assert "July event" not in descriptions

    def test_range_with_no_matches_returns_empty(self, client):
        resp = client.get("/api/events/range?start=1999-01-01&end=1999-12-31")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_range_without_params_returns_all(self, client):
        client.post("/api/events/", json={"date": "2026-06-15", "description": "Unbounded event"})
        resp = client.get("/api/events/range")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
