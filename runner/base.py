"""
Shared utilities for AEO browser runners.
Uses Camoufox (Firefox with C-level anti-detection) instead of vanilla Chromium.
Residential proxy routed via RESIDENTIAL_PROXY_URL env var.
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

API_BASE  = os.getenv("AEO_API", "http://localhost:8000")
# Cloud mode: runner is on Cloud Run when AEO_API points at a remote host.
# Must check both "localhost" and "127.0.0.1" — either can be used in local dev.
# (DATABASE_URL is not available in the runner job — only in the API service.)
_CLOUD    = not (API_BASE.startswith("http://localhost") or API_BASE.startswith("http://127.0.0.1"))

# ── Log buffer (cloud mode: lines flushed to API via heartbeat) ───────────────
_log_buffer: list[str] = []
_log_lock   = threading.Lock()

def _log(msg: str) -> None:
    """Print a log line and buffer it for heartbeat flush in cloud mode."""
    print(msg, flush=True)
    if _CLOUD:
        with _log_lock:
            _log_buffer.append(msg)

def _flush_logs() -> list[str]:
    """Drain and return buffered log lines."""
    with _log_lock:
        lines = _log_buffer.copy()
        _log_buffer.clear()
    return lines

_runner_dir    = Path("/tmp/runner") if _CLOUD else Path(__file__).parent
CHECKPOINT_DIR = _runner_dir / "checkpoints"
FLAGS_DIR      = _runner_dir / "flags"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
FLAGS_DIR.mkdir(parents=True, exist_ok=True)


# ── Proxy config ──────────────────────────────────────────────────────────────

def _proxy_config() -> dict | None:
    """
    Build a Playwright proxy dict from RESIDENTIAL_PROXY_URL.
    Expected format: http://user:pass@host:port  or  http://host:port
    Returns None if env var is not set (no proxy).
    """
    raw = os.getenv("RESIDENTIAL_PROXY_URL", "").strip()
    if not raw:
        return None
    try:
        p = urlparse(raw)
        cfg: dict = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
        if p.username:
            cfg["username"] = p.username
        if p.password:
            cfg["password"] = p.password
        return cfg
    except Exception as exc:
        print(f"  [proxy] Could not parse RESIDENTIAL_PROXY_URL: {exc}")
        return None


# ── Screenshot capture ────────────────────────────────────────────────────────

def post_screenshot(page, worker_id: str, name: str, label: str = "") -> None:
    """Capture JPEG screenshot and upload to backend. Never raises."""
    try:
        raw  = page.screenshot(type="jpeg", quality=60)
        data = base64.b64encode(raw).decode()
        requests.post(
            f"{API_BASE}/api/runner/screenshot",
            json={"worker_id": worker_id, "name": name, "data": data, "label": label},
            timeout=10,
        )
    except Exception:
        pass


# ── API calls ─────────────────────────────────────────────────────────────────

def fetch_session(platform: str) -> tuple:
    try:
        r = requests.get(
            f"{API_BASE}/api/accounts/claim",
            params={"platform": platform},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("found"):
            return data["account_id"], data["storage_state"]
    except Exception as exc:
        print(f"  [session] Could not fetch stored session: {exc}")
    return None, None


def register(name: str, platform: str, account_hint: str = None) -> str:
    # CLOUD_RUN_EXECUTION is set automatically by GCP on Cloud Run Jobs.
    # Persisting it lets the API cancel the job from any service instance.
    execution_name = os.getenv("CLOUD_RUN_EXECUTION", "")
    r = requests.post(f"{API_BASE}/api/runner/register", json={
        "name": name, "platform": platform, "account_hint": account_hint,
        "execution_name": execution_name or None,
    }, timeout=10)
    r.raise_for_status()
    return r.json()["worker_id"]


def claim(
    worker_id: str, platform: str, batch_size: int = 100,
    prompt_ids: list = None, session_id: str = None,
) -> dict:
    r = requests.post(f"{API_BASE}/api/runner/claim", json={
        "worker_id": worker_id, "platform": platform, "batch_size": batch_size,
        "prompt_ids": prompt_ids, "session_id": session_id,
    }, timeout=10)
    r.raise_for_status()
    return r.json()


def post_result(
    worker_id: str, batch_id: str, prompt_id: int, platform: str,
    raw_response: str, citations: list = None,
    latency_ms: int = 0, error: str = None,
) -> dict:
    payload = {
        "worker_id": worker_id, "batch_id": batch_id, "prompt_id": prompt_id,
        "platform": platform, "raw_response": raw_response or "",
        "citations": citations or [], "latency_ms": latency_ms, "error": error,
    }
    for attempt in range(3):
        try:
            r = requests.post(f"{API_BASE}/api/runner/result", json=payload, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            if attempt == 2:
                raise
            print(f"  [warn] result post attempt {attempt + 1} failed: {exc}. Retrying…")
            time.sleep(3)


def send_heartbeat(worker_id: str, batch_id: str, completed: int,
                   status: str = "running") -> bool:
    """Send a heartbeat. Returns True if the server wants the runner to stop."""
    payload: dict = {
        "worker_id": worker_id, "batch_id": batch_id,
        "completed": completed, "status": status,
    }
    lines = _flush_logs()
    if lines:
        payload["log_lines"] = lines
    try:
        r = requests.post(f"{API_BASE}/api/runner/heartbeat", json=payload, timeout=5)
        if r.ok:
            data = r.json()
            if not data.get("ok", True) and data.get("stop"):
                _log("  [heartbeat] Server signalled stop — exiting gracefully.")
                return True
    except Exception:
        pass
    return False


def complete(worker_id: str, batch_id: str, paused_s: int = 0) -> None:
    requests.post(f"{API_BASE}/api/runner/complete", json={
        "worker_id": worker_id, "batch_id": batch_id, "paused_s": paused_s,
    }, timeout=10).raise_for_status()


# ── Login gate (local only) ───────────────────────────────────────────────────

def signal_needs_login(worker_id: str, platform: str, name: str) -> None:
    (FLAGS_DIR / f"{platform}_{name}.needs_login").touch()
    send_heartbeat(worker_id, "", 0, status="waiting_login")
    print("  [login] Browser is open — log in, then click 'Login Complete' in the Research Command Center.")


def wait_if_paused(platform: str, name: str, worker_id: str,
                   batch_id: str, completed: int) -> int:
    pause_flag = FLAGS_DIR / f"{platform}_{name}.pause"
    if not pause_flag.exists():
        return 0
    print("  ⏸  Paused — waiting for resume signal from Research Command Center…")
    t_pause = time.time()
    while pause_flag.exists():
        send_heartbeat(worker_id, batch_id, completed, status="paused")
        time.sleep(5)
    elapsed_s = int(time.time() - t_pause)
    send_heartbeat(worker_id, batch_id, completed, status="running")
    print(f"  ▶  Resuming after {elapsed_s}s pause…\n")
    return elapsed_s


def wait_for_login_signal(platform: str, name: str, timeout_s: int = 600) -> None:
    ok_flag    = FLAGS_DIR / f"{platform}_{name}.login_ok"
    needs_flag = FLAGS_DIR / f"{platform}_{name}.needs_login"
    deadline   = time.time() + timeout_s
    print(f"  [login] Waiting for dashboard confirmation (up to {timeout_s // 60} min)…")
    while time.time() < deadline:
        if ok_flag.exists():
            ok_flag.unlink(missing_ok=True)
            needs_flag.unlink(missing_ok=True)
            print("  [login] ✓ Login confirmed. Continuing.\n")
            return
        time.sleep(2)
    raise TimeoutError(
        f"Login confirmation not received within {timeout_s}s. "
        "Click 'Login Complete' in the Research Command Center after logging in."
    )


# ── Checkpoint ────────────────────────────────────────────────────────────────

def _cp_path(platform: str, name: str) -> Path:
    return CHECKPOINT_DIR / f"{platform}_{name}.json"


def load_checkpoint(platform: str, name: str):
    path = _cp_path(platform, name)
    if path.exists():
        d = json.loads(path.read_text())
        return d.get("batch_id"), set(d.get("done", []))
    return None, set()


def save_checkpoint(platform: str, name: str, batch_id: str, done: set) -> None:
    _cp_path(platform, name).write_text(json.dumps({
        "batch_id": batch_id, "done": list(done),
    }))


def clear_checkpoint(platform: str, name: str) -> None:
    p = _cp_path(platform, name)
    if p.exists():
        p.unlink()


# ── Background heartbeat ──────────────────────────────────────────────────────

class Heartbeat:
    def __init__(self, worker_id: str, batch_id: str):
        self.worker_id       = worker_id
        self.batch_id        = batch_id
        self.completed       = 0
        self._stop           = threading.Event()
        self._server_stopped = threading.Event()  # set when server returns stop=True
        self._thread         = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def should_exit(self) -> bool:
        """True if the server sent a stop signal on the last heartbeat."""
        return self._server_stopped.is_set()

    def _loop(self):
        while not self._stop.wait(30):
            stop_requested = send_heartbeat(self.worker_id, self.batch_id, self.completed)
            if stop_requested:
                self._server_stopped.set()
                self._stop.set()
                break


# ── Browser-closed error detection ───────────────────────────────────────────

def _is_browser_closed(exc: Exception) -> bool:
    """
    Return True if the exception signals that the browser process was killed
    (e.g. OOM), rather than a page-level error that a retry within the same
    browser session could fix.
    """
    msg = str(exc).lower()
    return any(phrase in msg for phrase in (
        "target page, context or browser has been closed",
        "browser has been closed",
        "target closed",
        "connection closed",
        "browsercontext.close",
        "playwright._impl._errors",
    ))


# ── Main orchestrator ─────────────────────────────────────────────────────────

def run_batch(
    platform: str, name: str, batch_size: int, run_prompt_fn,
    prompt_ids: list = None, session_id: str = None,
):
    """
    Orchestrates a full batch run using Camoufox (Firefox anti-detect browser).
    Optional residential proxy via RESIDENTIAL_PROXY_URL env var.
    """
    from camoufox.sync_api import Camoufox

    _log(f"\n{'='*60}")
    _log(f"  AEO Browser Runner — {platform.upper()}")
    _log(f"  Worker: {name}  |  API: {API_BASE}")
    _log(f"{'='*60}\n")

    _log("[1/5] Registering worker…")
    worker_id = register(name, platform)
    _log(f"  worker_id: {worker_id}")

    saved_batch_id, done_ids = load_checkpoint(platform, name)
    if saved_batch_id and done_ids:
        _log(f"[2/5] Resuming — {len(done_ids)} prompts already done.")
    else:
        _log("[2/5] No checkpoint, starting fresh.")

    _log(f"[3/5] Claiming batch (up to {batch_size} prompts)…")
    batch = claim(worker_id, platform, batch_size, prompt_ids=prompt_ids, session_id=session_id)

    if not batch.get("batch_id"):
        _log("  All prompts already claimed. Nothing to do.")
        return

    batch_id = batch["batch_id"]
    prompts  = batch["prompts"]

    if done_ids:
        remaining = [p for p in prompts if p["id"] not in done_ids]
        _log(f"  Claimed {len(prompts)}, {len(done_ids)} already done → {len(remaining)} to run.")
        prompts = remaining
    else:
        _log(f"  Claimed {len(prompts)} prompts.")

    if not prompts:
        _log("  Nothing left to run.")
        complete(worker_id, batch_id)
        clear_checkpoint(platform, name)
        return

    hb           = Heartbeat(worker_id, batch_id)
    hb.completed = len(done_ids)

    _log("\n[4/5] Checking for stored browser session…")
    account_id, storage_state_json = fetch_session(platform)
    stored_session = None
    if storage_state_json:
        try:
            stored_session = json.loads(storage_state_json)
            _log(f"  Found stored session (account {account_id}) — skipping login gate.")
        except Exception as exc:
            _log(f"  [warn] Could not parse stored session JSON: {exc}")

    proxy = _proxy_config()
    if proxy:
        _log(f"  Residential proxy: {proxy['server']}")
    else:
        _log("  No proxy configured (RESIDENTIAL_PROXY_URL not set).")

    headless = _CLOUD or bool(stored_session)
    if not headless:
        _log("  No stored session — opening visible browser for manual login.")

    camoufox_kwargs: dict = {
        "headless": "virtual" if headless else False,
    }
    if proxy:
        camoufox_kwargs["proxy"] = proxy

    ctx_kwargs: dict = {
        "user_agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) "
            "Gecko/20100101 Firefox/125.0"
        ),
        "viewport": {"width": 1280, "height": 900},
    }
    if stored_session:
        ctx_kwargs["storage_state"] = stored_session

    _log(f"\n[5/5] Running {len(prompts)} prompts…\n")
    completed_count  = len(done_ids)
    failed_count     = 0
    total_paused_s   = 0
    prompt_idx       = 0          # position in prompts list; survives browser restarts
    browser_restarts = 0          # how many times we have re-launched the browser
    _MAX_RESTARTS    = 5   # arbitrary ceiling; 5 crashes in one batch indicates a structural problem

    hb.start()

    # ── Browser restart loop ──────────────────────────────────────────────────
    while prompt_idx < len(prompts) and not hb.should_exit():
        if browser_restarts > _MAX_RESTARTS:
            _log(f"  ✗ Too many browser restarts ({_MAX_RESTARTS}) — aborting "
                 f"{len(prompts) - prompt_idx} remaining prompt(s).")
            for p in prompts[prompt_idx:]:
                failed_count += 1
                post_result(
                    worker_id=worker_id, batch_id=batch_id,
                    prompt_id=p["id"], platform=platform,
                    raw_response="", error="Browser kept crashing — aborted.",
                )
            break

        if browser_restarts > 0:
            _log(f"\n  ⟳ Browser restart {browser_restarts}/{_MAX_RESTARTS} "
                 f"(resuming at prompt {prompt_idx + 1}/{len(prompts)})…")
            time.sleep(15)  # brief pause before restarting to let any rate-limiting or session issues settle
        else:
            _log(f"\n[5/5] Opening browser "
                 f"(headless={headless}, engine=Firefox/Camoufox)…")

        browser_died = False

        with Camoufox(**camoufox_kwargs) as browser:
            context = browser.new_context(**ctx_kwargs)
            context.on("dialog", lambda d: d.accept())
            page = context.new_page()

            try:
                run_prompt_fn(page, None, setup=True, worker_id=worker_id)
                post_screenshot(page, worker_id, name,
                                label="[setup] Initial page state after navigation")
            except Exception as setup_exc:
                _log(f"  ✗ Browser setup failed: {setup_exc}")
                browser_died = True

            # Login gate — only on first browser start (restarts always have stored session)
            if not browser_died and browser_restarts == 0:
                if stored_session:
                    send_heartbeat(worker_id, batch_id, hb.completed, status="running")
                else:
                    signal_needs_login(worker_id, platform, name)
                    wait_for_login_signal(platform, name)
                    send_heartbeat(worker_id, batch_id, hb.completed, status="running")

            # ── Inner prompt loop (within this browser session) ───────────────
            while prompt_idx < len(prompts) and not browser_died and not hb.should_exit():
                total_paused_s += wait_if_paused(
                    platform, name, worker_id, batch_id, completed_count
                )

                i           = prompt_idx + 1
                prompt      = prompts[prompt_idx]
                prompt_id   = prompt["id"]
                prompt_text = prompt["text"]
                label       = prompt.get("label", f"prompt {prompt_id}")

                _log(f"  [{i}/{len(prompts)}] {label[:60]}")

                t_start       = time.time()
                last_error    = None
                response_text = citations = latency_ms = None

                for attempt in range(3):
                    try:
                        response_text, citations, latency_ms = run_prompt_fn(
                            page, prompt_text, setup=False, worker_id=worker_id
                        )
                        last_error = None
                        break
                    except Exception as exc:
                        if _is_browser_closed(exc):
                            _log(f"    ⚡ Browser process closed at prompt {i} "
                                 f"— scheduling restart")
                            browser_died = True
                            break  # break attempt loop; prompt will retry after restart
                        last_error = exc
                        shot_label = (f"[{i}/{len(prompts)}] attempt {attempt+1} "
                                      f"failed: {type(exc).__name__}")
                        post_screenshot(page, worker_id, name, label=shot_label)
                        if attempt < 2:
                            wait_s = 30 * (attempt + 1)  # exponential backoff: 30s, 60s
                            _log(f"    ↺ Attempt {attempt + 1}/3 failed: {exc}. "
                                 f"Retrying in {wait_s}s…")
                            time.sleep(wait_s)
                        else:
                            _log(f"    ✗ All 3 attempts failed: {exc}")

                if browser_died:
                    # Prompt will be retried on next browser restart — do not advance index
                    break

                if last_error is None:
                    post_result(
                        worker_id=worker_id, batch_id=batch_id,
                        prompt_id=prompt_id, platform=platform,
                        raw_response=response_text,
                        citations=citations, latency_ms=latency_ms,
                    )
                    completed_count += 1
                    hb.completed = completed_count
                    done_ids.add(prompt_id)
                    save_checkpoint(platform, name, batch_id, done_ids)
                    elapsed = time.time() - t_start
                    chars   = len(response_text) if response_text else 0
                    _log(f"    ✓ {chars} chars in {elapsed:.1f}s")
                else:
                    failed_count += 1
                    post_result(
                        worker_id=worker_id, batch_id=batch_id,
                        prompt_id=prompt_id, platform=platform,
                        raw_response="", error=str(last_error),
                    )

                prompt_idx += 1
                # Flush logs immediately after each prompt so the UI updates promptly
                send_heartbeat(worker_id, batch_id, completed_count)

                if prompt_idx < len(prompts) and not browser_died:
                    time.sleep(12)  # inter-prompt cooldown: avoids rate-limiting and lets the page settle

        # ── End of Camoufox context ───────────────────────────────────────────
        if browser_died:
            browser_restarts += 1

    hb.stop()
    complete(worker_id, batch_id, total_paused_s)
    clear_checkpoint(platform, name)

    _log(f"\n{'='*60}")
    _log(f"  Done — {completed_count} captured, {failed_count} failed")
    _log(f"{'='*60}\n")
