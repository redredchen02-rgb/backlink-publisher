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


def _alive_recheck(result):
    # 7b: the freshly-published URL probes alive (the happy confirming recheck).
    return {"verdict": "alive", "live_url": result.get("published_url"),
            "target_url": result.get("target_url")}


def _stripped_recheck(result):
    # 7b: the new URL was eaten immediately → S7 treadmill.
    return {"verdict": "link_stripped", "live_url": result.get("published_url"),
            "target_url": result.get("target_url")}


def _wait(reg, job_id, timeout=4.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = reg.poll(job_id)
        if p and p["status"] != "running":
            return p
        time.sleep(0.01)
    return reg.poll(job_id)


def _issue_and_start(reg, seeds, targets, *, publish_fn, persist_fn=lambda e: None,
                     recheck_fn=_alive_recheck):
    gap = _gap_fn(seeds)
    tok = reg.issue_confirm_token(store=None, gap_fn=gap)["confirm_token"]
    job = reg.start_republish(
        selected_targets=targets, confirm_token=tok, store=None,
        gap_fn=gap, publish_fn=publish_fn, persist_fn=persist_fn,
        recheck_fn=recheck_fn, sticky_platforms=("blogger",),
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
                             publish_fn=_ok_publish, recheck_fn=_alive_recheck,
                             sticky_platforms=("blogger",))
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
                             publish_fn=slow, recheck_fn=_alive_recheck,
                             sticky_platforms=("blogger",))
    t2 = reg.issue_confirm_token(store=None, gap_fn=gap)["confirm_token"]
    with pytest.raises(UsageError, match="already running"):
        reg.start_republish(selected_targets=["https://51acgs.com/comic/117"],
                            confirm_token=t2, store=None, gap_fn=gap,
                            publish_fn=slow, sticky_platforms=("blogger",))
    hold.set()
    _wait(reg, job.id)


def test_two_concurrent_tokens_cannot_both_start():
    # P1 regression: conflict-check + nonce-pop + job-insert must be ONE atomic
    # lock block. With a split (check in one block, insert in another) two
    # distinct valid tokens fired concurrently could both pass the check and both
    # start a worker → double-publish. Exactly one must win; the other rejected.
    reg = KeepaliveJobRegistry()
    seeds = [_seed("https://51acgs.com/comic/117")]
    gap = _gap_fn(seeds)
    barrier = threading.Barrier(2)
    release = threading.Event()
    results = []

    def slow_pub(s):
        release.wait(timeout=3)
        return _ok_publish(s)

    def fire():
        tok = reg.issue_confirm_token(store=None, gap_fn=gap)["confirm_token"]
        barrier.wait()  # align both threads at the start_republish call
        try:
            job = reg.start_republish(
                selected_targets=["https://51acgs.com/comic/117"], confirm_token=tok,
                store=None, gap_fn=gap, publish_fn=slow_pub, recheck_fn=_alive_recheck,
                sticky_platforms=("blogger",),
            )
            results.append(("ok", job.id))
        except UsageError as exc:
            results.append(("rejected", str(exc)))

    threads = [threading.Thread(target=fire) for _ in range(2)]
    for t in threads:
        t.start()
    # keep the winner's worker blocked until BOTH threads have raced through
    # start_republish, so the loser deterministically observes status=="running".
    deadline = time.time() + 5
    while len(results) < 2 and time.time() < deadline:
        time.sleep(0.01)
    release.set()
    for t in threads:
        t.join(timeout=5)

    oks = [r for r in results if r[0] == "ok"]
    rejected = [r for r in results if r[0] == "rejected"]
    assert len(oks) == 1, f"expected exactly one start, got {results}"
    assert len(rejected) == 1 and "already running" in rejected[0][1]
    assert len([j for j in reg._jobs.values() if j.kind == "republish"]) == 1


# ── 7b: auto-recheck of the freshly-published URLs (S6 confirm / S7 treadmill) ──

def test_auto_recheck_confirms_new_url_alive_s6():
    reg = KeepaliveJobRegistry()
    seeds = [_seed("https://51acgs.com/comic/117")]
    p = _issue_and_start(reg, seeds, ["https://51acgs.com/comic/117"],
                         publish_fn=_ok_publish, recheck_fn=_alive_recheck)
    assert p["state"] == "all_success" and p["phase"] == "done"
    # the new URL was probed and proven live — not a blind "published" claim.
    assert p["reverify_total"] == 1 and p["reverify_done"] == 1
    assert p["confirmed_alive"] == 1 and p["restripped"] == 0
    assert p["reverified"][0]["verdict"] == "alive"


def test_fresh_url_restripped_terminates_in_treadmill_s7():
    reg = KeepaliveJobRegistry()
    seeds = [_seed("https://51acgs.com/comic/117")]
    # publish succeeds, but the confirming recheck finds the new link already gone.
    p = _issue_and_start(reg, seeds, ["https://51acgs.com/comic/117"],
                         publish_fn=_ok_publish, recheck_fn=_stripped_recheck)
    assert p["published"] == 1                 # the publish itself succeeded
    assert p["state"] == "treadmill"           # S7: platform-unreliable terminal
    assert p["restripped"] == 1 and p["confirmed_alive"] == 0


def test_only_published_urls_are_rechecked():
    reg = KeepaliveJobRegistry()
    seeds = [_seed("https://51acgs.com/comic/117"), _seed("https://51acgs.com/comic/528")]
    seen = []

    def track(result):
        seen.append(result["published_url"])
        return _alive_recheck(result)

    def mixed(seed):
        return _ok_publish(seed) if "117" in seed["target_url"] else _fail_publish(seed)

    p = _issue_and_start(reg, seeds, [s["target_url"] for s in seeds],
                         publish_fn=mixed, recheck_fn=track)
    # only the one successful publish is rechecked; the failed one never is.
    assert p["reverify_total"] == 1 and len(seen) == 1
    assert p["state"] == "partial_success"     # a publish failure still beats no-publish


def test_reverify_error_is_probe_error_not_a_treadmill():
    reg = KeepaliveJobRegistry()
    seeds = [_seed("https://51acgs.com/comic/117")]

    def boom(result):
        raise RuntimeError("network down")

    p = _issue_and_start(reg, seeds, ["https://51acgs.com/comic/117"],
                         publish_fn=_ok_publish, recheck_fn=boom)
    # a probe failure is indeterminate — it must NOT be read as a re-strip (S7).
    assert p["restripped"] == 0 and p["state"] == "all_success"
    assert p["reverified"][0]["verdict"] == "probe_error"


# ── 7b: write_verified_at called by _default_reverify (Issue B fix) ──────────


def test_default_reverify_updates_verified_at_on_alive(tmp_path):
    """_default_reverify must call write_verified_at so the ledger sees the new
    alive link on the next build_ledger call; without it liveness stays 'unverified'
    and live_dofollow_platforms is never populated for the republished article."""
    from unittest.mock import patch

    from backlink_publisher.events import EventStore
    from backlink_publisher.events.kinds import LINK_RECHECKED
    from webui_app.services.keepalive_job import _default_reverify

    store = EventStore(path=tmp_path / "events.db")
    url = "https://taiwanmanga2026.blogspot.com/test-reverify.html"
    target = "https://51acgs.com/comic/117"

    def _fake_probe(record, probe):
        return {**record, "verdict": "alive", "confirmed_dofollow": True, "reason": None}

    with patch("webui_app.services.keepalive_job.recheck_link", _fake_probe):
        verdict = _default_reverify(
            {"target_url": target, "platform": "blogger", "published_url": url},
            store,
        )

    assert verdict["verdict"] == "alive"

    # emit_recheck must have written a link.rechecked event.
    events = list(store.query("SELECT COUNT(*) AS n FROM events WHERE kind = ?", (LINK_RECHECKED,)))
    assert events[0]["n"] == 1, "emit_recheck not called"

    # write_verified_at must have set articles.verified_at for the alive verdict.
    arts = list(store.query("SELECT verified_at FROM articles WHERE live_url LIKE ?", ("%test-reverify%",)))
    assert arts, "article not registered by _ensure_article"
    assert arts[0]["verified_at"], "write_verified_at was not called by _default_reverify"
