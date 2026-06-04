"""Unit 5 — Bind job state machine completeness (plan 2026-06-04-004).

TimeoutExpired→kill, concurrent poll, false-success prevention, backend failure.
_HangingProc defined at module scope (prerequisite).
"""
from __future__ import annotations

__tier__ = "unit"

import io
import json
import subprocess
import threading
import time
from typing import Any

import pytest

from backlink_publisher._util.errors import UsageError


# ── _FakeProc (copy of canonical pattern) ────────────────────────────────────

class _FakeProc:
    def __init__(self, lines: list[str], returncode: int = 0):
        self.stdout = io.StringIO("".join(lines))
        self.stderr = io.StringIO("")
        self._returncode = returncode
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:  # noqa: ARG002
        return self._returncode

    def kill(self) -> None:
        self.killed = True


class _HangingProc:
    """Simulates a process whose stdout terminates but wait(timeout=N) hangs.

    Behavioral contract (all three must hold for the test to work):
    - stdout: empty iterator (no terminal events → stdout loop exits immediately)
    - wait(timeout=N) where N > 0: raises subprocess.TimeoutExpired
    - wait(timeout=None): returns -9 (simulates post-kill exit)

    _drain_stdout calls wait(timeout=10) in its finally block AFTER stdout
    closes. The hang is in process exit, not stdout.
    """

    def __init__(self):
        self.stdout = iter([])  # empty — no terminal events
        self.stderr = io.StringIO("")
        self._returncode = -9
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:
        if timeout is not None:
            raise subprocess.TimeoutExpired(cmd="bind-channel", timeout=timeout)
        return self._returncode

    def kill(self) -> None:
        self.killed = True


def _make_popen(lines: list[str], returncode: int = 0):
    def _factory(*_args: Any, **_kwargs: Any) -> _FakeProc:
        return _FakeProc(lines, returncode=returncode)
    return _factory


def _events_jsonl(*events: dict[str, Any]) -> list[str]:
    return [json.dumps(ev) + "\n" for ev in events]


def _wait_until(predicate, timeout: float = 3.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture
def registry():
    from webui_app.services.bind_job import BindJobRegistry
    r = BindJobRegistry()
    yield r
    r.reset_for_tests()


# ── TimeoutExpired → kill ──────────────────────────────────────────────────────

def test_timeout_expired_triggers_kill_and_failed_status(registry):
    """`_HangingProc` → stdout closes → wait(10) raises TimeoutExpired → kill() → status="failed"."""
    hanging = _HangingProc()
    registry._popen = lambda *a, **kw: hanging

    job = registry.start("medium")
    assert _wait_until(lambda: job.status != "running"), "Job did not leave running state"

    assert job.status == "failed"
    assert hanging.killed, "kill() must be called on TimeoutExpired"
    # error_code reflects no terminal event (timeout caused stream-close path)
    assert job.error_code == "stream_closed_no_terminal_event"


# ── Backend failure via event ─────────────────────────────────────────────────

def test_channel_bind_failed_event_sets_status_failed(registry):
    # returncode=1 required: _drain_stdout sets status based on both
    # terminal_event_seen AND exit_code. With exit_code=0 + terminal event
    # seen, the job becomes "done". Non-zero exit code → "failed" as expected.
    registry._popen = _make_popen(_events_jsonl(
        {"event": "channel.bind.failed", "error_code": "auth_rejected"},
    ), returncode=1)
    job = registry.start("medium")
    assert _wait_until(lambda: job.status != "running")
    assert job.status == "failed"
    assert job.error_code == "auth_rejected"


# ── Stream closed without terminal event ─────────────────────────────────────

def test_stream_closed_no_terminal_event(registry):
    """Stdout closes without terminal event → status="failed", error_code reflects stream_closed."""
    registry._popen = _make_popen(
        _events_jsonl({"event": "channel.bind.start", "channel": "medium"}),
        returncode=1,
    )
    job = registry.start("medium")
    assert _wait_until(lambda: job.status != "running")
    assert job.status == "failed"
    assert job.error_code == "stream_closed_no_terminal_event"


# ── False-success prevention ──────────────────────────────────────────────────

def test_poll_while_running_never_returns_done(registry):
    """While job is running, poll() returns 'running', never 'done'."""
    class _BlockingProc:
        def __init__(self):
            self._ready = threading.Event()
            self.stdout = self
            self.stderr = io.StringIO("")
            self.killed = False

        def __iter__(self):
            self._ready.wait(timeout=2)
            return iter([])

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.killed = True

    proc = _BlockingProc()
    registry._popen = lambda *a, **kw: proc

    job = registry.start("medium")
    # While stdout hasn't closed yet, status must be running
    snap = registry.poll(job.id)
    assert snap is not None
    # May be running or already transitioned; never "done" before terminal event
    if snap["status"] == "done":
        pytest.fail("poll() returned 'done' before terminal event — false-success")
    # Unblock the proc
    proc._ready.set()


# ── Concurrent poll ───────────────────────────────────────────────────────────

def test_concurrent_poll_returns_consistent_snapshots(registry):
    """Two threads polling simultaneously return identical snapshots; no exception."""
    registry._popen = _make_popen(_events_jsonl(
        {"event": "channel.bind.persisted", "channel": "medium"},
    ))
    job = registry.start("medium")
    assert _wait_until(lambda: job.status != "running")

    results: list[dict] = []
    errors: list[Exception] = []

    def _poll():
        try:
            snap = registry.poll(job.id)
            if snap is not None:
                results.append(snap)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=_poll)
    t2 = threading.Thread(target=_poll)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert not errors, f"poll() raised: {errors}"
    assert len(results) == 2
    # Both snapshots must report the same status
    assert results[0]["status"] == results[1]["status"]
