"""
Runner process manager — local subprocess mode only.

Spawns Playwright/Camoufox runner as a child subprocess.

Communication:
  - Status : workers call /api/runner/heartbeat → SQLite DB
  - Logs   : line-buffered file in runner/logs/
  - Flags  : files in runner/flags/
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────
_two_up       = Path(__file__).parent.parent
_three_up     = Path(__file__).parent.parent.parent
_project_root = _two_up if (_two_up / "runner").exists() else _three_up
_runner_base  = _project_root / "runner"

if not (_project_root / "runner").exists():
    import warnings
    warnings.warn(
        f"runner/ directory not found under {_project_root}. "
        "Subprocess launch will fail. "
        "Expected layout: <project_root>/runner/ alongside <project_root>/backend/",
        stacklevel=1,
    )

PROJECT_ROOT = _project_root
FLAGS_DIR    = _runner_base / "flags"
LOGS_DIR     = _runner_base / "logs"

FLAGS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ── In-memory process table ───────────────────────────────────────────────────
_procs: dict[str, dict] = {}   # name → {"proc": Popen, "log_fh": file, "platform": str}


# ── Public API ────────────────────────────────────────────────────────────────

def launch(
    platform: str,
    name: str,
    batch_size: int = 100,
    prompt_ids: list = None,
    session_id: str = None,
) -> str:
    """Spawn a runner subprocess. Returns the PID as a string."""
    return str(_launch_subprocess(platform, name, batch_size, prompt_ids, session_id))


def stop(name: str) -> None:
    _stop_subprocess(name)


def signal_login_ready(platform: str, name: str) -> None:
    """Creates login_ok flag so the runner continues past the login gate."""
    (FLAGS_DIR / f"{platform}_{name}.login_ok").touch()


def get_logs(platform: str, name: str, last_n: int = 80) -> list:
    """Return last N log lines from the runner log file."""
    log_path = LOGS_DIR / f"{platform}_{name}.log"
    if not log_path.exists():
        return []
    lines = log_path.read_text(errors="replace").splitlines()
    return lines[-last_n:]


def parse_log_progress(platform: str, name: str) -> dict:
    # COUPLING WARNING: these regexes must stay in sync with the log format
    # produced by runner/base.py (run_batch).  Specifically:
    #   running_re  → matches "[5/5] Running N prompts…"
    #   prompt_re   → matches "[i/N] <label>" lines emitted per prompt
    #   "✓" / "✗"  → success/failure markers from _log() calls
    #   "[login]"   → login-gate phase markers
    #   "Done —"    → final summary line
    # If any of those log strings change in base.py, update the patterns here.
    lines = get_logs(platform, name, last_n=500)
    total = current_index = done = failed = 0
    current_label = ""
    phase = "setup"
    running_re = re.compile(r"Running (\d+) prompts")
    prompt_re  = re.compile(r"\[(\d+)/(\d+)\]\s*(.*)")

    for line in lines:
        m = running_re.search(line)
        if m:
            total = int(m.group(1))
            phase = "running"
        m = prompt_re.search(line)
        if m:
            current_index = int(m.group(1))
            if not total:
                total = int(m.group(2))
            label = m.group(3).strip()
            if label:
                current_label = label
            phase = "running"
        if "✓" in line:
            done += 1
        if "✗" in line:
            failed += 1
        if "[login]" in line and "Waiting for dashboard" in line:
            phase = "login"
        if "[login]" in line and "Login confirmed" in line:
            phase = "running"
        if "Done —" in line:
            phase = "done"

    return {
        "current_index": current_index, "total": total,
        "done": done, "failed": failed,
        "current_label": current_label, "phase": phase,
    }


def is_alive(name: str) -> bool:
    if name not in _procs:
        pid_file = _pid_path(name)
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, 0)
                return True
            except (ProcessLookupError, PermissionError, ValueError):
                pass
        return False
    return _procs[name]["proc"].poll() is None


def pid_of(name: str) -> Optional[int]:
    entry = _procs.get(name)
    if entry:
        return entry["proc"].pid
    pid_file = _pid_path(name)
    if pid_file.exists():
        try:
            return int(pid_file.read_text().strip())
        except ValueError:
            pass
    return None


def needs_login(platform: str, name: str) -> bool:
    return (FLAGS_DIR / f"{platform}_{name}.needs_login").exists()


def pause(platform: str, name: str) -> None:
    (FLAGS_DIR / f"{platform}_{name}.pause").touch()


def resume(platform: str, name: str) -> None:
    flag = FLAGS_DIR / f"{platform}_{name}.pause"
    flag.unlink(missing_ok=True)


def is_paused(platform: str, name: str) -> bool:
    return (FLAGS_DIR / f"{platform}_{name}.pause").exists()


# ── Subprocess helpers ────────────────────────────────────────────────────────

def _launch_subprocess(
    platform: str, name: str, batch_size: int,
    prompt_ids: list = None, session_id: str = None,
) -> int:
    if name in _procs and _procs[name]["proc"].poll() is None:
        raise RuntimeError(f"Runner '{name}' is already running (pid {_procs[name]['proc'].pid}).")

    log_path = LOGS_DIR / f"{platform}_{name}.log"
    log_fh   = open(log_path, "w", buffering=1)

    cmd = [
        sys.executable, "-u", "-m", "runner.run",
        "--platform",   platform,
        "--name",       name,
        "--batch-size", str(batch_size),
        "--api",        os.getenv("AEO_API", "http://localhost:8000"),
    ]

    extra_env = {**os.environ}
    if prompt_ids:
        extra_env["AEO_PROMPT_IDS"] = ",".join(str(i) for i in prompt_ids)
    if session_id:
        extra_env["AEO_SESSION_ID"] = session_id

    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        env=extra_env,
    )
    _procs[name] = {"proc": proc, "log_fh": log_fh, "platform": platform}
    _pid_path(name).write_text(str(proc.pid))
    return proc.pid


def _stop_subprocess(name: str) -> None:
    platform = None
    if name in _procs:
        entry = _procs.pop(name)
        platform = entry.get("platform")
        try:
            entry["proc"].terminate()
        except Exception:
            pass
        try:
            entry["log_fh"].close()
        except Exception:
            pass
    pid_file = _pid_path(name)
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, ValueError):
            pass
        pid_file.unlink(missing_ok=True)
    if platform is None:
        platform = name.split("-")[0] if "-" in name else name
    _clear_flags(platform, name)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pid_path(name: str) -> Path:
    return LOGS_DIR / f"{name}.pid"


def _clear_flags(platform: str, name: str) -> None:
    for suffix in ("needs_login", "login_ok", "pause"):
        f = FLAGS_DIR / f"{platform}_{name}.{suffix}"
        if f.exists():
            f.unlink()
