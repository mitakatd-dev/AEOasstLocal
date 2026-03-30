from sqlalchemy import Column, Integer, String, Text, Boolean, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.database import Base


class Prompt(Base):
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True, index=True)
    label = Column(Text, nullable=False)
    text = Column(Text, nullable=False)
    variant_group = Column(Text, nullable=True)
    query_type = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    runs = relationship("Run", back_populates="prompt")
    notes = relationship("PromptNote", back_populates="prompt", cascade="all, delete-orphan")


class Run(Base):
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, index=True)
    prompt_id = Column(Integer, ForeignKey("prompts.id"), nullable=False)
    triggered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    status = Column(String, default="running")
    # Groups all runs triggered together into one research session
    session_id = Column(String, nullable=True, index=True)
    # "api" = direct API call | "browser" = Playwright web capture
    collection_method = Column(String, default="api")

    prompt = relationship("Prompt", back_populates="runs")
    results = relationship("Result", back_populates="run")


class Result(Base):
    __tablename__ = "results"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False)
    llm = Column(String, nullable=False)
    raw_response = Column(Text, nullable=True)
    mentioned = Column(Boolean, default=False)
    position_score = Column(Float, nullable=True)
    sentiment = Column(String, nullable=True)
    competitors_mentioned = Column(Text, default="[]")
    error = Column(Text, nullable=True)
    latency_ms = Column(Integer, default=0)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)

    run = relationship("Run", back_populates="results")


class Experiment(Base):
    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=False)
    hypothesis = Column(Text, nullable=False)
    variant_group = Column(Text, nullable=False)
    status = Column(String, default="active")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    concluded_at = Column(DateTime, nullable=True)
    conclusion = Column(Text, nullable=True)


class PromptNote(Base):
    __tablename__ = "prompt_notes"

    id = Column(Integer, primary_key=True, index=True)
    prompt_id = Column(Integer, ForeignKey("prompts.id"), nullable=False)
    note = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    prompt = relationship("Prompt", back_populates="notes")


class AppSetting(Base):
    """Key-value store for admin-configurable settings (API keys, company config)."""
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)


class ExternalEvent(Base):
    __tablename__ = "external_events"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, nullable=False)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class BrowserAccount(Base):
    """
    Stored Playwright session (cookies + localStorage) for a platform account.
    Enables headless browser runners on Cloud Run without interactive login.
    Multiple accounts per platform — round-robin rotation via last_used_at.
    """
    __tablename__ = "browser_accounts"

    id = Column(String, primary_key=True)   # UUID string
    platform = Column(String, nullable=False)  # 'chatgpt', 'gemini', 'perplexity'
    label = Column(String, nullable=False)     # e.g. email for human identification
    storage_state = Column(Text, nullable=True)  # JSON from context.storage_state()
    status = Column(String, default="active")    # 'active', 'expired', 'pending'
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class BrowserWorker(Base):
    __tablename__ = "browser_workers"

    id = Column(String, primary_key=True)  # UUID string
    name = Column(String, nullable=False)  # e.g. "chatgpt-1"
    platform = Column(String, nullable=False)  # 'chatgpt', 'gemini', 'perplexity'
    account_hint = Column(String, nullable=True)  # e.g. email prefix for identification
    status = Column(String, default="idle")  # idle, running, paused, done, error
    last_heartbeat = Column(DateTime, nullable=True)
    registered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    execution_name = Column(String, nullable=True)  # Cloud Run Job execution resource name
    log_lines = Column(Text, nullable=True)          # Accumulated log lines (cloud mode)

    batches = relationship("WorkerBatch", back_populates="worker")


class WorkerBatch(Base):
    __tablename__ = "worker_batches"

    id = Column(String, primary_key=True)  # UUID string
    worker_id = Column(String, ForeignKey("browser_workers.id"), nullable=False)
    platform = Column(String, nullable=False)
    prompt_ids = Column(Text, nullable=False)  # JSON array of prompt IDs
    session_id = Column(String, nullable=True, index=True)  # links to Run.session_id
    total = Column(Integer, default=0)
    completed = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    status = Column(String, default="claimed")  # claimed, running, completed, error
    claimed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
    total_paused_s = Column(Integer, default=0)  # seconds paused during this batch

    worker = relationship("BrowserWorker", back_populates="batches")


class WorkerScreenshot(Base):
    """Latest screenshot per worker — upserted on each capture so only one row per worker."""
    __tablename__ = "worker_screenshots"

    worker_name = Column(String, primary_key=True)  # e.g. "chatgpt-1"
    data = Column(Text, nullable=True)              # base64 JPEG
    label = Column(Text, nullable=True)
    captured_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Citation(Base):
    """Structured citation/source extracted from an LLM response (API or browser)."""
    __tablename__ = "citations"

    id = Column(Integer, primary_key=True, index=True)
    result_id = Column(Integer, ForeignKey("results.id"), nullable=False, index=True)
    url = Column(Text, nullable=False)
    title = Column(Text, nullable=True)
    domain = Column(String, nullable=True)   # netloc extracted from url
    position = Column(Integer, default=0)    # order in which citation appeared
    collection_method = Column(String, default="api")  # "api" or "browser"
