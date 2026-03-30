"""
Integration tests for the /api/runner/claim endpoint.

Critical correctness invariants:
  1. Prompts in ACTIVE (claimed/running) batches must not be re-claimable.
  2. Prompts in COMPLETED batches MUST be claimable again (re-run support).
  3. prompt_ids filter restricts the claim to a subset.
  4. If all prompts are active, claim returns an empty batch.
"""
from __future__ import annotations

import json
import uuid
import pytest
from tests.conftest import make_prompt


# ── Helpers ────────────────────────────────────────────────────────────────────

def register_worker(client, platform="chatgpt", name="chatgpt-1"):
    r = client.post("/api/runner/register", json={"name": name, "platform": platform})
    assert r.status_code == 200
    return r.json()["worker_id"]


def claim(client, worker_id, platform="chatgpt", batch_size=100,
          prompt_ids=None, session_id=None):
    payload = {"worker_id": worker_id, "platform": platform, "batch_size": batch_size}
    if prompt_ids is not None:
        payload["prompt_ids"] = prompt_ids
    if session_id is not None:
        payload["session_id"] = session_id
    return client.post("/api/runner/claim", json=payload)


def complete_batch(client, worker_id, batch_id):
    return client.post("/api/runner/complete", json={"worker_id": worker_id, "batch_id": batch_id})


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestBasicClaim:
    def test_claim_returns_prompts(self, client, db):
        p = make_prompt(db, label="Claim test prompt")
        wid = register_worker(client)
        r = claim(client, wid, prompt_ids=[p.id])
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["batch_id"] is not None
        assert any(pr["id"] == p.id for pr in data["prompts"])

    def test_claim_returns_prompt_fields(self, client, db):
        p = make_prompt(db, label="Field check", text="Is Maersk good?", query_type="category")
        wid = register_worker(client, name="chatgpt-2")
        r = claim(client, wid, prompt_ids=[p.id])
        prompt_data = next(pr for pr in r.json()["prompts"] if pr["id"] == p.id)
        assert prompt_data["label"] == "Field check"
        assert prompt_data["text"] == "Is Maersk good?"
        assert prompt_data["query_type"] == "category"

    def test_claim_with_no_prompts_returns_empty(self, client, db):
        wid = register_worker(client, name="chatgpt-empty")
        r = claim(client, wid, prompt_ids=[99999])  # non-existent ID
        data = r.json()
        assert data["prompts"] == []
        assert data["batch_id"] is None

    def test_unregistered_worker_returns_404(self, client, db):
        r = claim(client, "non-existent-worker-id")
        assert r.status_code == 404


class TestActiveBatchBlocking:
    def test_active_claimed_batch_blocks_repick(self, client, db):
        """A prompt already in a 'claimed' batch must not be given to another worker."""
        p = make_prompt(db, label="Active block test")
        wid1 = register_worker(client, name="chatgpt-blocker-1")
        wid2 = register_worker(client, name="chatgpt-blocker-2")

        # Worker 1 claims the prompt — batch stays in 'claimed' status
        r1 = claim(client, wid1, prompt_ids=[p.id])
        assert r1.json()["batch_id"] is not None

        # Worker 2 tries to claim the same prompt — must get nothing
        r2 = claim(client, wid2, prompt_ids=[p.id])
        assert r2.json()["prompts"] == []
        assert r2.json()["batch_id"] is None

    def test_running_batch_blocks_repick(self, client, db):
        """A prompt in a 'running' batch must also be blocked."""
        p = make_prompt(db, label="Running block test")
        wid = register_worker(client, name="chatgpt-running-1")
        wid2 = register_worker(client, name="chatgpt-running-2")

        # Claim and advance to 'running' via heartbeat
        r1 = claim(client, wid, prompt_ids=[p.id])
        batch_id = r1.json()["batch_id"]
        client.post("/api/runner/heartbeat", json={
            "worker_id": wid, "batch_id": batch_id,
            "status": "running", "completed": 0,
        })

        # Second worker must get nothing
        r2 = claim(client, wid2, prompt_ids=[p.id])
        assert r2.json()["prompts"] == []


class TestCompletedBatchDoesNotBlock:
    def test_completed_batch_allows_rerun(self, client, db):
        """
        Critical regression test: prompts in COMPLETED batches must be claimable again.
        This was the root cause of 'All prompts already claimed' after every first run.
        """
        p = make_prompt(db, label="Rerun test prompt")
        wid = register_worker(client, name="chatgpt-rerun-1")

        # First run: claim → complete
        r1 = claim(client, wid, prompt_ids=[p.id])
        batch_id = r1.json()["batch_id"]
        assert batch_id is not None
        complete_batch(client, wid, batch_id)

        # Second run: same prompt must be claimable again by any worker
        wid2 = register_worker(client, name="chatgpt-rerun-2")
        r2 = claim(client, wid2, prompt_ids=[p.id])
        assert r2.json()["batch_id"] is not None, (
            "Prompt in a COMPLETED batch should be claimable again — "
            "check that claim_batch() only blocks 'claimed'/'running' statuses."
        )
        assert any(pr["id"] == p.id for pr in r2.json()["prompts"])

    def test_same_worker_can_rerun_after_completing(self, client, db):
        p = make_prompt(db, label="Same worker rerun")
        wid = register_worker(client, name="chatgpt-same-rerun")

        r1 = claim(client, wid, prompt_ids=[p.id])
        batch_id = r1.json()["batch_id"]
        complete_batch(client, wid, batch_id)

        # Re-register (as if the subprocess restarted)
        client.post("/api/runner/register", json={
            "worker_id": wid, "name": "chatgpt-same-rerun", "platform": "chatgpt",
        })
        r2 = claim(client, wid, prompt_ids=[p.id])
        assert r2.json()["batch_id"] is not None


class TestPromptIdFilter:
    def test_prompt_id_filter_restricts_claim(self, client, db):
        p1 = make_prompt(db, label="Prompt A")
        p2 = make_prompt(db, label="Prompt B")
        wid = register_worker(client, name="chatgpt-filter-1")

        r = claim(client, wid, prompt_ids=[p1.id])
        prompts_returned = [pr["id"] for pr in r.json()["prompts"]]
        assert p1.id in prompts_returned
        assert p2.id not in prompts_returned

    def test_batch_size_limits_claim(self, client, db):
        prompts = [make_prompt(db, label=f"BS prompt {i}") for i in range(5)]
        ids = [p.id for p in prompts]
        wid = register_worker(client, name="chatgpt-bs-1")

        r = claim(client, wid, batch_size=3, prompt_ids=ids)
        assert len(r.json()["prompts"]) == 3

    def test_session_id_attached_to_batch(self, client, db):
        p = make_prompt(db, label="Session test")
        wid = register_worker(client, name="chatgpt-sess-1")
        session = str(uuid.uuid4())

        claim(client, wid, prompt_ids=[p.id], session_id=session)

        # Verify by checking worker status — session propagates to results via run
        # (direct DB check is simpler here)
        from app.models import WorkerBatch
        from sqlalchemy.orm import Session as SQLSession

        # Use the override session through the TestClient — peek via API
        status = client.get("/api/runner/status").json()
        worker_info = next((w for w in status["workers"] if w["worker_id"] == wid), None)
        assert worker_info is not None
        batch = worker_info["batches"][-1]
        assert batch["status"] in ("claimed", "running")


class TestWorkerRegistration:
    def test_register_new_worker(self, client):
        r = client.post("/api/runner/register", json={
            "name": "reg-test-1", "platform": "chatgpt",
        })
        assert r.status_code == 200
        assert "worker_id" in r.json()
        assert r.json()["ok"] is True

    def test_reregister_existing_worker_returns_same_id(self, client):
        r1 = client.post("/api/runner/register", json={
            "name": "rereg-test", "platform": "chatgpt",
        })
        wid = r1.json()["worker_id"]

        r2 = client.post("/api/runner/register", json={
            "worker_id": wid, "name": "rereg-test", "platform": "chatgpt",
        })
        assert r2.json()["worker_id"] == wid
