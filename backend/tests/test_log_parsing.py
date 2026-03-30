"""
Unit tests for runner_manager.parse_log_progress()

Tests the regex-based log parser without spawning any real processes.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch

from app.runner_manager import parse_log_progress


def _parse(lines: list[str]) -> dict:
    """Helper: feed fake log lines to parse_log_progress via mock."""
    with patch("app.runner_manager.get_logs", return_value=lines):
        return parse_log_progress("chatgpt", "chatgpt-1")


class TestEmptyLog:
    def test_empty_log_defaults(self):
        result = _parse([])
        assert result["current_index"] == 0
        assert result["total"] == 0
        assert result["done"] == 0
        assert result["failed"] == 0
        assert result["current_label"] == ""
        assert result["phase"] == "setup"


class TestRunningLine:
    def test_detects_total_from_running_line(self):
        result = _parse(["Running 15 prompts for chatgpt"])
        assert result["total"] == 15
        assert result["phase"] == "running"

    def test_running_line_with_different_count(self):
        result = _parse(["Running 42 prompts"])
        assert result["total"] == 42


class TestPromptIndexLine:
    def test_detects_current_index(self):
        result = _parse(["  [3/10] Which company is best?"])
        assert result["current_index"] == 3
        assert result["total"] == 10

    def test_detects_label(self):
        result = _parse(["  [1/5] Container shipping leaders"])
        assert result["current_label"] == "Container shipping leaders"

    def test_index_advances_with_multiple_lines(self):
        lines = [
            "  [1/10] First prompt",
            "    ✓ 200 chars in 2.1s",
            "  [2/10] Second prompt",
            "    ✓ 300 chars in 1.8s",
        ]
        result = _parse(lines)
        assert result["current_index"] == 2

    def test_label_updates_to_last_seen(self):
        lines = [
            "  [1/5] First label",
            "  [2/5] Second label",
        ]
        result = _parse(lines)
        assert result["current_label"] == "Second label"

    def test_total_inferred_from_index_line_when_no_running_line(self):
        result = _parse(["  [4/20] Some prompt"])
        assert result["total"] == 20


class TestSuccessFailureCount:
    def test_counts_checkmark_lines(self):
        lines = [
            "    ✓ 120 chars in 1.5s",
            "    ✓ 350 chars in 2.0s",
            "    ✓ 80 chars in 0.9s",
        ]
        result = _parse(lines)
        assert result["done"] == 3

    def test_counts_cross_lines(self):
        lines = [
            "    ✗ Error: timeout waiting for response",
            "    ✗ Error: network failure",
        ]
        result = _parse(lines)
        assert result["failed"] == 2

    def test_mixed_success_and_failure(self):
        lines = [
            "    ✓ 200 chars in 1.0s",
            "    ✗ Error: timeout",
            "    ✓ 150 chars in 0.8s",
            "    ✗ Error: network",
            "    ✓ 300 chars in 2.1s",
        ]
        result = _parse(lines)
        assert result["done"] == 3
        assert result["failed"] == 2

    def test_generic_error_message_not_counted_as_failure(self):
        # Only ✗ lines count as failures — not generic "Error" mentions
        lines = [
            "Connecting to ChatGPT... Error: retry",
            "WARNING: error in setup",
        ]
        result = _parse(lines)
        assert result["failed"] == 0


class TestPhaseDetection:
    def test_setup_phase_is_default(self):
        result = _parse(["Starting runner…"])
        assert result["phase"] == "setup"

    def test_login_phase_detected(self):
        result = _parse(["  [login] Waiting for dashboard — browser is open"])
        assert result["phase"] == "login"

    def test_running_phase_after_login_confirmed(self):
        lines = [
            "  [login] Waiting for dashboard",
            "  [login] Login confirmed. Continuing.",
        ]
        result = _parse(lines)
        assert result["phase"] == "running"

    def test_done_phase_at_end(self):
        lines = [
            "Running 5 prompts",
            "  [1/5] First",
            "    ✓ ok",
            "Done — 5 captured, 0 failed",
        ]
        result = _parse(lines)
        assert result["phase"] == "done"

    def test_running_phase_from_prompt_line(self):
        result = _parse(["  [1/3] A prompt label"])
        assert result["phase"] == "running"


class TestFullBatchRealistic:
    def test_realistic_log_sequence(self):
        lines = [
            "============================================================",
            "  AEO Browser Runner — CHATGPT",
            "  Worker: chatgpt-1  |  API: http://localhost:8000",
            "============================================================",
            "",
            "[1/5] Registering worker…",
            "  worker_id: abc-123",
            "[2/5] No checkpoint, starting fresh.",
            "[3/5] Claiming batch (up to 100 prompts)…",
            "  Claimed 8 prompts.",
            "[4/5] Opening browser and waiting for login…",
            "  [login] Browser is open — log in, then click 'Login Complete'.",
            "  [login] Waiting for dashboard confirmation (up to 10 min)…",
            "  [login] ✓ Login confirmed. Continuing.",
            "",
            "[5/5] Running 8 prompts…",
            "",
            "  [1/8] Best container shipping line",
            "    ✓ 420 chars in 3.2s",
            "  [2/8] Which freight company is recommended",
            "    ✓ 610 chars in 4.1s",
            "  [3/8] Top logistics providers",
            "    ✗ Error: response timeout",
            "  [4/8] Global shipping market leaders",
            "    ✓ 380 chars in 2.9s",
        ]
        result = _parse(lines)
        assert result["total"] == 8
        assert result["current_index"] == 4
        # 3 prompt ✓ lines + 1 login-confirmation ✓ line = 4 total ✓ chars
        assert result["done"] == 4
        assert result["failed"] == 1
        assert result["current_label"] == "Global shipping market leaders"
        assert result["phase"] == "running"
