"""G5a rehydrate path — same-process tab reopen can restore in-flight recheck job polling.

Covers:
1. Happy path: job running mid-flight → running_job("recheck") returns snapshot
   with job_id, status=="running", checked, verdict_counts, per_host non-None.
2. Edge case: no running job → running_job() returns None.
3. Edge case: job reaches terminal state → running_job() returns None.
4. Integration (rehydrate): calling running_job() twice (simulating tab reopen)
   returns same snapshot — all fields needed for frontend polling are present.
"""
__tier__ = "integration"

import threading
import time

import pytest

from backlink_publisher.events import EventStore
from webui_app.services.keepalive_job import KeepaliveJobRegistry


# ── helpers ──────────────────────────────────────────────────────────────────

def _cand(article_id, verdict="alive", host="51acgs.com"):
    return {
        "live_url": f"https://taiwanmanga2026.blogspot.com/{article_id}.html",
        "target_url": "https://51acgs.com/comic/117",
        "host": host,
        "article_id": article_id,
        "platform": "blogger",
        "_verdict": verdict,
    }


def _probe(cand):
    return {**cand, "verdict": cand["_verdict"], "reason": None}


def _wait_terminal(reg, job_id, timeout=4.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = reg.poll(job_id)
        if p and p["status"] != "running":
            return p
        time.sleep(0.01)
    return reg.poll(job_id)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    return EventStore(path=tmp_path / "events.db")


# ── tests ─────────────────────────────────────────────────────────────────────

def test_running_job_returns_snapshot_mid_flight(store):
    """Happy path: running_job('recheck') returns snapshot while job is in flight."""
    reg = KeepaliveJobRegistry()
    started = threading.Event()
    release = threading.Event()

    def gated(cand):
        started.set()
        release.wait(timeout=3)
        return _probe(cand)

    cands = [_cand(f"a{i}") for i in range(3)]
    reg.start_recheck(store=store, candidates=cands, probe_fn=gated)

    # Wait until probe is mid-flight
    assert started.wait(2), "probe never started"

    snap = reg.running_job(kind="recheck")
    assert snap is not None, "running_job should return snapshot while running"
    assert snap["job_id"] is not None
    assert snap["status"] == "running"
    assert snap["checked"] is not None
    assert snap["verdict_counts"] is not None
    assert snap["per_host"] is not None

    release.set()
    _wait_terminal(reg, snap["job_id"])


def test_running_job_returns_none_when_no_job(store):
    """Edge case: no running job → running_job() returns None."""
    reg = KeepaliveJobRegistry()
    assert reg.running_job(kind="recheck") is None


def test_running_job_returns_none_after_terminal(store):
    """Edge case: job reaches terminal state → running_job() returns None."""
    reg = KeepaliveJobRegistry()
    cands = [_cand("a0")]
    job = reg.start_recheck(store=store, candidates=cands, probe_fn=_probe)
    p = _wait_terminal(reg, job.id)
    assert p["status"] == "done"

    # After terminal, running_job should find no running job
    snap = reg.running_job(kind="recheck")
    assert snap is None, "running_job should return None once job is terminal"


def test_running_job_rehydrate_consistency(store):
    """Integration (rehydrate): two calls to running_job() return consistent snapshots.

    Simulates a tab reopen: the second call to running_job() (from a fresh
    request context) must return the same job_id and all polling fields.
    """
    reg = KeepaliveJobRegistry()
    started = threading.Event()
    release = threading.Event()

    def gated(cand):
        started.set()
        release.wait(timeout=3)
        return _probe(cand)

    cands = [_cand(f"a{i}") for i in range(4)]
    reg.start_recheck(store=store, candidates=cands, probe_fn=gated)

    assert started.wait(2), "probe never started"

    # First call — initial page load
    snap1 = reg.running_job(kind="recheck")
    assert snap1 is not None

    # Second call — simulates tab reopen / page refresh
    snap2 = reg.running_job(kind="recheck")
    assert snap2 is not None

    # Both calls must refer to the same job
    assert snap1["job_id"] == snap2["job_id"]

    # All fields needed for frontend polling must be present in both snapshots
    required_fields = {"job_id", "status", "checked", "verdict_counts", "per_host"}
    assert required_fields.issubset(snap1.keys()), f"missing fields in snap1: {required_fields - snap1.keys()}"
    assert required_fields.issubset(snap2.keys()), f"missing fields in snap2: {required_fields - snap2.keys()}"

    release.set()
    _wait_terminal(reg, snap1["job_id"])
