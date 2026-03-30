import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

_database_url = os.environ.get("DATABASE_URL")

if _database_url:
    # Cloud Run: PostgreSQL via Cloud SQL unix socket.
    # pool_pre_ping:  validate connection before checkout (catches most stale connections)
    # pool_recycle:   hard-expire connections after 30 min so they never go stale
    #                 during idle periods (e.g. user switches tabs for >5 min)
    # pool_size/max:  keep pool small — each Cloud Run instance holds its own pool
    engine = create_engine(
        _database_url,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=5,
        max_overflow=2,
    )
    DATABASE_URL = _database_url
else:
    # Local dev: SQLite
    _default_data_dir = Path(__file__).parent.parent.parent / "data"
    _data_dir = Path(os.environ.get("DATABASE_DIR", str(_default_data_dir)))
    _data_dir.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{_data_dir.resolve() / 'db.sqlite'}"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    from app.models import Prompt, Run, Result, Experiment, PromptNote, BrowserWorker, WorkerBatch, BrowserAccount  # noqa: F401
    from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
    try:
        Base.metadata.create_all(bind=engine)
    except (IntegrityError, OperationalError, ProgrammingError):
        # Race condition: two Cloud Run instances starting simultaneously both attempt
        # CREATE TABLE. PostgreSQL creates a composite type per table, so the second
        # concurrent CREATE TABLE hits a pg_type UniqueViolation. Safe to ignore —
        # the first instance already created the schema.
        pass
    _migrate(engine)


def _migrate(eng):
    """Add columns to existing tables if missing."""
    insp = inspect(eng)
    if "prompts" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("prompts")}
        with eng.begin() as conn:
            if "variant_group" not in cols:
                conn.execute(text("ALTER TABLE prompts ADD COLUMN variant_group TEXT"))
            if "query_type" not in cols:
                conn.execute(text("ALTER TABLE prompts ADD COLUMN query_type TEXT"))
    if "worker_batches" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("worker_batches")}
        with eng.begin() as conn:
            if "session_id" not in cols:
                conn.execute(text("ALTER TABLE worker_batches ADD COLUMN session_id TEXT"))
            if "total_paused_s" not in cols:
                conn.execute(text("ALTER TABLE worker_batches ADD COLUMN total_paused_s INTEGER DEFAULT 0"))
    if "runs" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("runs")}
        with eng.begin() as conn:
            if "session_id" not in cols:
                conn.execute(text("ALTER TABLE runs ADD COLUMN session_id TEXT"))
            if "collection_method" not in cols:
                conn.execute(text("ALTER TABLE runs ADD COLUMN collection_method TEXT DEFAULT 'api'"))
    if "results" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("results")}
        with eng.begin() as conn:
            if "prompt_tokens" not in cols:
                conn.execute(text("ALTER TABLE results ADD COLUMN prompt_tokens INTEGER DEFAULT 0"))
            if "completion_tokens" not in cols:
                conn.execute(text("ALTER TABLE results ADD COLUMN completion_tokens INTEGER DEFAULT 0"))
            if "total_tokens" not in cols:
                conn.execute(text("ALTER TABLE results ADD COLUMN total_tokens INTEGER DEFAULT 0"))
            if "cost_usd" not in cols:
                conn.execute(text("ALTER TABLE results ADD COLUMN cost_usd REAL DEFAULT 0.0"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
