"""R1 / Unit 7 (7a) — keep-alive republish job security core (plan 2026-06-04-001).

The republish job re-derives the gap set server-side (never trusts posted ids),
drops non-sticky destinations, consumes a single-use confirm nonce bound to the
gap fingerprint, persists published_unverified before recheck, and returns a
structured partial result (never ok-on-partial). Drives the job function with
injected fakes — no real network/subprocess.
"""
__tier__ = "integration"

import threading
import time

import pytest

from backlink_publisher._util.errors import UsageError
from webui_app.services.keepalive_job import KeepaliveJobRegistry


def _seed(target, platform="blogger"):
    return {"target_url": target, "platform": platform, "main_domain": "https://51acgs.com",
            "language": "zh-CN", "url_mode": "A", "publish_mode": "draft"}


def _gap_fn(seeds):
    return lambda store: (seeds, [])


def _ok_publish(seed):
    return {"target_url": seed["target_url"], "platform": seed["platform"],
            "published_url": f"https://taiwanmanga2026.blogspot.com/{seed['target_url'][-3:]}.html",
            "status": "published", "error": None}


def _fail_publish(seed):
    return {"target_url": seed["target_url"], "platform": seed["platform"],
            "published_url": "", "status": "failed", "error": "blogger 429"}


def _wait(reg, job_id, timeout=4.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = reg.poll(job_id)
        if p and p["status"] != "running":
            return p
        time.sleep(0.01)
    return reg.poll(job_id)


def _issue_and_start(reg, seeds, targets, *, publish_fn, persist_fn=lambda e: None):
    gap = _gap_fn(seeds)
    tok = reg.issue_confirm_token(store=None, gap_fn=gap)["confirm_token"]
    job = reg.start_republish(
        selected_targets=targets, confirm_token=tok, store=None,
        gap_fn=gap, publish_fn=publish_fn, persist_fn=persist_fn, sticky_platforms=("blogger",),
    )
    return _wait(reg, job.id)


def test_happy_publish_persists_and_succeeds():
    reg = KeepaliveJobRegistry()
    persisted = []
    seeds = [_seed("https://51acgs.com/comic/117")]
    p = _issue_and_start(reg, seeds, ["https://51acgs.com/comic/117"],
                         publish_fn=_ok_publish, persist_fn=persisted.append)
    assert p["status"] == "done" and p["state"] == "all_success"
    assert p["published"] == 1 and p["failed"] == 0
    # persist-before-recheck: a published_unverified row was written.
    assert persisted and persisted[0]["status"] == "published_unverified"


def test_partial_is_not_reported_as_success():
    reg = KeepaliveJobRegistry()
    seeds = [_seed("https://51acgs.com/comic/117"), _seed("https://51acgs.com/comic/528")]

    def mixed(seed):
        return _ok_publish(seed) if "117" in seed["target_url"] else _fail_publish(seed)

    p = _issue_and_start(reg, seeds, [s["target_url"] for s in seeds], publish_fn=mixed)
    assert p["state"] == "partial_success"
    assert p["published"] == 1 and p["failed"] == 1
    assert any(r["status"] == "failed" and r["error"] for r in p["results"])


def test_unselected_target_is_dropped():
    reg = KeepaliveJobRegistry()
    seeds = [_seed("https://51acgs.com/comic/117"), _seed("https://51acgs.com/comic/528")]
    # Only select 117 → 528 is not republished even though it's a gap.
    p = _issue_and_start(reg, seeds, ["https://51acgs.com/comic/117"], publish_fn=_ok_publish)
    assert p["total"] == 1 and p["published"] == 1


def test_invalid_or_reused_token_rejected():
    reg = KeepaliveJobRegistry()
    seeds = [_seed("https://51acgs.com/comic/117")]
    gap = _gap_fn(seeds)
    with pytest.raises(UsageError, match="confirm token"):
        reg.start_republish(selected_targets=["https://51acgs.com/comic/117"],
                            confirm_token="not-a-real-token", store=None,
                            gap_fn=gap, publish_fn=_ok_publish, sticky_platforms=("blogger",))


def test_stale_gap_set_rejects_token():
    reg = KeepaliveJobRegistry()
    issued_seeds = [_seed("https://51acgs.com/comic/117")]
    tok = reg.issue_confirm_token(store=None, gap_fn=_gap_fn(issued_seeds))["confirm_token"]
    # The gap set changed before confirm (the link went live → fewer seeds).
    changed = _gap_fn([])
    with pytest.raises(UsageError, match="gap set changed"):
        reg.start_republish(selected_targets=["https://51acgs.com/comic/117"],
                            confirm_token=tok, store=None, gap_fn=changed,
                            publish_fn=_ok_publish, sticky_platforms=("blogger",))


def test_token_is_single_use():
    reg = KeepaliveJobRegistry()
    seeds = [_seed("https://51acgs.com/comic/117")]
    gap = _gap_fn(seeds)
    tok = reg.issue_confirm_token(store=None, gap_fn=gap)["confirm_token"]
    job = reg.start_republish(selected_targets=["https://51acgs.com/comic/117"],
                             confirm_token=tok, store=None, gap_fn=gap,
                             publish_fn=_ok_publish, sticky_platforms=("blogger",))
    _wait(reg, job.id)
    with pytest.raises(UsageError, match="confirm token"):  # replay rejected
        reg.start_republish(selected_targets=["https://51acgs.com/comic/117"],
                            confirm_token=tok, store=None, gap_fn=gap,
                            publish_fn=_ok_publish, sticky_platforms=("blogger",))


def test_concurrent_republish_conflicts():
    reg = KeepaliveJobRegistry()
    seeds = [_seed("https://51acgs.com/comic/117")]
    gap = _gap_fn(seeds)
    hold = threading.Event()

    def slow(seed):
        hold.wait(timeout=3)
        return _ok_publish(seed)

    t1 = reg.issue_confirm_token(store=None, gap_fn=gap)["confirm_token"]
    job = reg.start_republish(selected_targets=["https://51acgs.com/comic/117"],
                             confirm_token=t1, store=None, gap_fn=gap,
                             publish_fn=slow, sticky_platforms=("blogger",))
    t2 = reg.issue_confirm_token(store=None, gap_fn=gap)["confirm_token"]
    with pytest.raises(UsageError, match="already running"):
        reg.start_republish(selected_targets=["https://51acgs.com/comic/117"],
                            confirm_token=t2, store=None, gap_fn=gap,
                            publish_fn=slow, sticky_platforms=("blogger",))
    hold.set()
    _wait(reg, job.id)
