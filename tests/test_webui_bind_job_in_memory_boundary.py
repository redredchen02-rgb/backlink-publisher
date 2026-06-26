"""Unit 6 — Bind job in-memory limitation and reset boundary (plan 2026-06-04-004).

v1 in-memory only — if v2 adds persistence, update this test.
reset_for_tests() clears all jobs. reap_orphans() is a documented no-op.
"""
from __future__ import annotations

__tier__ = "unit"

import io
import json
import time
from typing import Any

import pytest

# ── helpers (same pattern as test_webui_bind_job_service.py) ─────────────────

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


@pytest.fixture(autouse=True)
def _reset(request):
    """Autouse teardown: clear registry state after every test to prevent leakage."""
    from webui_app.services.bind_job import registry
    yield
    registry.reset_for_tests()


@pytest.fixture
def reg():
    from webui_app.services.bind_job import registry
    registry.reset_for_tests()
    return registry


# ── reset clears completed job ────────────────────────────────────────────────

def test_completed_job_gone_after_reset(reg):
    """Start → terminal event → reset_for_tests() → poll returns not-found."""
    reg._popen = _make_popen(_events_jsonl(
        {"event": "channel.bind.persisted", "channel": "medium"},
    ))
    job = reg.start("medium")
    assert _wait_until(lambda: job.status != "running")
    assert job.status == "done"

    job_id = job.id
    reg.reset_for_tests()
    assert reg.poll(job_id) is None, "Completed job must not persist after reset"


# ── reset clears running job, no ghost channel lock ───────────────────────────

def test_running_job_gone_after_reset_no_ghost_lock(reg):
    """reset_for_tests() while job running → job gone; same channel re-startable."""
    import threading

    class _BlockingProc:
        def __init__(self):
            self._ready = threading.Event()
            self.stdout = self
            self.stderr = io.StringIO("")
            self.killed = True  # mark killed pre-emptively

        def __iter__(self):
            self._ready.wait(timeout=0.5)
            return iter([])

        def wait(self, timeout=None):
            return -1

        def kill(self):
            self.killed = True

    reg._popen = lambda *a, **kw: _BlockingProc()
    job = reg.start("medium")
    assert job.status == "running"

    reg.reset_for_tests()
    assert reg.poll(job.id) is None

    # No ghost channel lock: new job for same channel succeeds
    reg._popen = _make_popen(_events_jsonl(
        {"event": "channel.bind.persisted", "channel": "medium"},
    ))
    new_job = reg.start("medium")
    assert new_job.id != job.id


# ── reap_orphans is a documented no-op ───────────────────────────────────────

def test_reap_orphans_does_not_remove_jobs(reg):
    """reap_orphans() with completed jobs in registry → count unchanged."""
    from webui_app.services.bind_job import reap_orphans

    reg._popen = _make_popen(_events_jsonl(
        {"event": "channel.bind.persisted", "channel": "medium"},
    ))
    j1 = reg.start("medium")
    assert _wait_until(lambda: j1.status != "running")

    # Capture poll result before reap
    pre_poll = reg.poll(j1.id)
    assert pre_poll is not None

    reap_orphans()

    # Job still present after no-op reap
    post_poll = reg.poll(j1.id)
    assert post_poll is not None, "reap_orphans() must not remove in-memory jobs (v1 no-op)"
    assert post_poll["status"] == pre_poll["status"]


# ── poll on nonexistent id ─────────────────────────────────────────────────────

def test_poll_nonexistent_returns_none_no_exception(reg):
    """poll('unknown') on empty registry → None; no KeyError."""
    result = reg.poll("abc-unknown-id")
    assert result is None


# ── reset then start same channel succeeds ───────────────────────────────────

def test_reset_then_start_same_channel(reg):
    """reset_for_tests() → start new job for same channel → succeeds."""
    reg._popen = _make_popen(_events_jsonl(
        {"event": "channel.bind.persisted", "channel": "medium"},
    ))
    j1 = reg.start("medium")
    assert _wait_until(lambda: j1.status != "running")

    reg.reset_for_tests()

    reg._popen = _make_popen(_events_jsonl(
        {"event": "channel.bind.persisted", "channel": "medium"},
    ))
    j2 = reg.start("medium")
    assert j2.id != j1.id
    assert _wait_until(lambda: j2.status != "running")
    assert j2.status == "done"
