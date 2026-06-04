"""R1 / Unit 5 — keep-alive async recheck job (plan 2026-06-04-001).

Drives the job *function* directly with an injected fake probe (no network):
progress checked→total, probe_error recorded as check-failed, cancel mid-run
leaves a partial, a second start conflicts, a worker exception ends in an error
state (never a hang), and every result is written as an append-only
link.rechecked event.
"""
__tier__ = "integration"

import threading
import time

import pytest

from backlink_publisher._util.errors import UsageError
from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import LINK_RECHECKED
from webui_app.services.keepalive_job import KeepaliveJobRegistry


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
    # Echo the candidate into a recheck-result shape emit_recheck accepts.
    return {**cand, "verdict": cand["_verdict"], "reason": None}


def _wait_terminal(reg, job_id, timeout=4.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = reg.poll(job_id)
        if p and p["status"] != "running":
            return p
        time.sleep(0.01)
    return reg.poll(job_id)


@pytest.fixture
def store(tmp_path):
    return EventStore(path=tmp_path / "events.db")


def test_progress_and_verdict_rollup(store):
    reg = KeepaliveJobRegistry()
    cands = [_cand(f"a{i}", verdict="alive") for i in range(3)] + [_cand("a3", verdict="link_stripped")]
    job = reg.start_recheck(store=store, candidates=cands, probe_fn=_probe)
    p = _wait_terminal(reg, job.id)
    assert p["status"] == "done"
    assert p["checked"] == 4 and p["total"] == 4
    assert p["verdict_counts"] == {"alive": 3, "link_stripped": 1}
    assert p["per_host"] == {"51acgs.com": 4}


def test_probe_error_recorded_as_check_failed(store):
    reg = KeepaliveJobRegistry()

    def boom(cand):
        raise RuntimeError("dns nope")

    job = reg.start_recheck(store=store, candidates=[_cand("a0")], probe_fn=boom)
    p = _wait_terminal(reg, job.id)
    assert p["status"] == "done"
    assert p["verdict_counts"] == {"probe_error": 1}


def test_appends_link_rechecked_events(store):
    reg = KeepaliveJobRegistry()
    job = reg.start_recheck(store=store, candidates=[_cand("a0"), _cand("a1")], probe_fn=_probe)
    _wait_terminal(reg, job.id)
    rows = list(store.query("SELECT COUNT(*) AS n FROM events WHERE kind = ?", (LINK_RECHECKED,)))
    assert rows[0]["n"] == 2


def test_cancel_mid_run_leaves_partial(store):
    reg = KeepaliveJobRegistry()
    started = threading.Event()
    release = threading.Event()

    def gated(cand):
        started.set()
        release.wait(timeout=3)
        return _probe(cand)

    cands = [_cand(f"a{i}") for i in range(5)]
    job = reg.start_recheck(store=store, candidates=cands, probe_fn=gated)
    assert started.wait(2)            # first probe is in flight
    reg.cancel(job.id)
    release.set()                     # let the in-flight probe finish
    p = _wait_terminal(reg, job.id)
    assert p["status"] == "cancelled"
    assert p["checked"] < p["total"]  # not all 5 probed


def test_second_start_conflicts(store):
    reg = KeepaliveJobRegistry()
    hold = threading.Event()

    def slow(cand):
        hold.wait(timeout=3)
        return _probe(cand)

    job = reg.start_recheck(store=store, candidates=[_cand("a0")], probe_fn=slow)
    with pytest.raises(UsageError):
        reg.start_recheck(store=store, candidates=[_cand("a1")], probe_fn=slow)
    hold.set()
    _wait_terminal(reg, job.id)


def test_worker_exception_ends_in_error_state(store):
    reg = KeepaliveJobRegistry()

    class BadList(list):
        def __len__(self):
            raise RuntimeError("len boom")

    job = reg.start_recheck(store=store, candidates=BadList([_cand("a0")]), probe_fn=_probe)
    p = _wait_terminal(reg, job.id)
    assert p["status"] == "error"
    assert "recheck job failed" in (p["error"] or "")


def test_poll_unknown_id_returns_none(store):
    reg = KeepaliveJobRegistry()
    assert reg.poll("deadbeef") is None
    assert reg.cancel("deadbeef") is None
