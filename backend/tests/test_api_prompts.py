"""
Integration tests for /api/prompts/ endpoints.
"""
from __future__ import annotations

import pytest
from tests.conftest import make_prompt


class TestListPrompts:
    def test_list_returns_200(self, client):
        r = client.get("/api/prompts/")
        assert r.status_code == 200

    def test_list_returns_list(self, client):
        assert isinstance(client.get("/api/prompts/").json(), list)


class TestCreatePrompt:
    def test_create_prompt_succeeds(self, client):
        r = client.post("/api/prompts/", json={
            "label": "New test prompt",
            "text": "Which shipping company is most reliable?",
            "query_type": "category",
        })
        assert r.status_code in (200, 201)
        data = r.json()
        assert data["label"] == "New test prompt"
        assert data["id"] is not None

    def test_create_prompt_missing_required_field_returns_422(self, client):
        r = client.post("/api/prompts/", json={"label": "No text field"})
        assert r.status_code == 422

    def test_create_prompt_with_variant_group(self, client):
        r = client.post("/api/prompts/", json={
            "label": "Variant A",
            "text": "Who leads container shipping?",
            "query_type": "category",
            "variant_group": "shipping-leaders",
        })
        assert r.status_code in (200, 201)
        assert r.json()["variant_group"] == "shipping-leaders"


class TestUpdatePrompt:
    def test_update_existing_prompt(self, client, db):
        p = make_prompt(db, label="Original label")
        r = client.put(f"/api/prompts/{p.id}", json={
            "label": "Updated label",
            "text": "Updated text",
        })
        assert r.status_code == 200
        assert r.json()["label"] == "Updated label"

    def test_update_nonexistent_prompt_returns_404(self, client):
        r = client.put("/api/prompts/999999", json={
            "label": "Doesn't matter",
            "text": "Doesn't matter",
        })
        assert r.status_code == 404

    def test_update_returns_all_fields(self, client, db):
        p = make_prompt(db, label="To update", query_type="category")
        r = client.put(f"/api/prompts/{p.id}", json={
            "label": "Updated",
            "text": "New text",
            "query_type": "problem",
        })
        data = r.json()
        assert data["query_type"] == "problem"
        assert data["id"] == p.id


class TestDeletePrompt:
    def test_delete_prompt_succeeds(self, client, db):
        p = make_prompt(db, label="To be deleted")
        r = client.delete(f"/api/prompts/{p.id}")
        assert r.status_code in (200, 204)

    def test_delete_nonexistent_prompt_returns_404(self, client):
        r = client.delete("/api/prompts/999998")
        assert r.status_code == 404
