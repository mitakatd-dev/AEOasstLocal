"""
Shared pytest fixtures for AEO Insights backend tests.

Uses an in-memory SQLite database with StaticPool so ALL sessions share
the same underlying connection (required for SQLite :memory: to work across
multiple sessions in the same process).

Tests are:
  - Isolated from production db.sqlite
  - Fast (no disk I/O)
  - Safe to run while the real backend is running
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


# ── Test engine — single shared connection via StaticPool ─────────────────────

def _make_test_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # share ONE connection so :memory: DB is visible everywhere
    )
    return engine


@pytest.fixture(scope="session")
def test_engine():
    """
    In-memory SQLite engine shared for the entire test session.
    All fixtures and code under test use the SAME connection via StaticPool.
    """
    engine = _make_test_engine()

    # Patch app.database to use this engine BEFORE anything imports it
    import app.database as db_module
    test_session_maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db_module.engine = engine
    db_module.SessionLocal = test_session_maker

    # Suppress the background LLM execution thread.
    # trigger_runs() spawns a daemon thread that calls real LLM APIs.  In tests
    # this races the shared StaticPool connection, corrupts the session state, and
    # causes PendingRollbackError in every subsequent test.  Tests only need to
    # verify that Run records are created — not that LLM results come back.
    import app.routers.runs as runs_module
    runs_module._run_in_background = lambda *args, **kwargs: None

    # Create schema
    from app.database import Base
    import app.models  # noqa: F401 — registers all ORM classes
    Base.metadata.create_all(bind=engine)

    yield engine
    engine.dispose()


@pytest.fixture
def db(test_engine):
    """
    Fresh session per test, rolled back afterwards for isolation.
    """
    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="session")
def client(test_engine):
    """
    FastAPI TestClient using the in-memory DB.
    Overrides get_db so every endpoint uses the test engine's sessions.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db

    Session = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# ── Factory helpers ────────────────────────────────────────────────────────────

def make_prompt(db, label="Test prompt", text="Which shipping company is best?",
                query_type="category", variant_group=None):
    from app.models import Prompt
    p = Prompt(label=label, text=text, query_type=query_type, variant_group=variant_group)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def make_run(db, prompt_id, status="completed", session_id=None,
             collection_method="api", triggered_at=None):
    from app.models import Run
    from datetime import datetime, timezone
    r = Run(
        prompt_id=prompt_id,
        status=status,
        session_id=session_id,
        collection_method=collection_method,
        triggered_at=triggered_at or datetime.now(timezone.utc),
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def make_result(db, run_id, llm="openai", mentioned=True, sentiment="positive",
                position_score=0.1, competitors_mentioned="[]", error=None):
    from app.models import Result
    res = Result(
        run_id=run_id,
        llm=llm,
        raw_response="Sample response text",
        mentioned=mentioned,
        position_score=position_score,
        sentiment=sentiment,
        competitors_mentioned=competitors_mentioned,
        error=error,
        latency_ms=500,
    )
    db.add(res)
    db.commit()
    db.refresh(res)
    return res


def make_citation(db, result_id, url="https://example.com", title="Example"):
    from app.models import Citation
    c = Citation(result_id=result_id, url=url, title=title, domain="example.com")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def make_browser_worker(db, name="chatgpt-1", platform="chatgpt", status="running"):
    import uuid
    from app.models import BrowserWorker
    w = BrowserWorker(
        id=str(uuid.uuid4()),
        name=name,
        platform=platform,
        status=status,
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


def make_worker_batch(db, worker_id, session_id=None, status="running", prompt_ids="[]"):
    import uuid
    from app.models import WorkerBatch
    b = WorkerBatch(
        id=str(uuid.uuid4()),
        worker_id=worker_id,
        platform="chatgpt",
        prompt_ids=prompt_ids,
        session_id=session_id,
        status=status,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b
