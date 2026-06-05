"""Tests for keepalive-run core chain (plan 2026-06-05-004 Units 1/2/3)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backlink_publisher.keepalive.chain import (
    run_cycle,
    _effective_sticky,
    _update_opt_stats,
)
from backlink_publisher.keepalive.run_state import KeepaliveRunState


# ── shared fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def state_dir(tmp_path):
    return tmp_path


@pytest.fixture
def run_state(state_dir):
    return KeepaliveRunState(data_dir=state_dir)


def _noop_probe(record):
    return {**record, "verdict": "probe_error", "reason": "test stub"}


# ── helper to build a minimal cycle call ──────────────────────────────────────


def _run(
    *,
    state_dir: Path,
    candidates=None,
    unverified=None,
    probe_fn=_noop_probe,
    status=None,
    rows=None,
    seeds=None,
    publish_fn=None,
    reverify_fn=None,
    dry_run=False,
    max_gaps=None,
    effective_sticky=("blogger",),
):
    """Run a cycle with all dependencies stubbed."""
    store = MagicMock()

    _candidates = candidates or []
    _unverified = unverified or []
    _status = status or {}
    _rows = rows or []
    _seeds_raw = seeds if seeds is not None else []
    _gaps = []

    def _plan(rows, per_target_status, opts, *, sticky_platforms=()):
        return _seeds_raw, _gaps

    def _emit(s, results):
        return len(results)

    def _vat(s, results):
        return 0

    def _default_publish(seed):
        return {
            "target_url": seed.get("target_url"),
            "platform": seed.get("platform"),
            "published_url": f"https://blogger.com/post/{seed.get('target_url', '')[:10]}",
            "status": "published",
            "error": None,
        }

    def _default_reverify(result):
        return {"verdict": "alive", "reason": "ok"}

    return run_cycle(
        store=store,
        dry_run=dry_run,
        max_gaps=max_gaps,
        config_dir=state_dir,
        select_candidates_fn=lambda s: _candidates,
        select_unverified_fn=lambda s: _unverified,
        probe_fn=probe_fn,
        derive_status_fn=lambda s: _status,
        build_ledger_fn=lambda s: _rows,
        emit_recheck_fn=_emit,
        write_verified_at_fn=_vat,
        publish_fn=publish_fn or _default_publish,
        reverify_fn=reverify_fn or _default_reverify,
        plan_gap_fn=_plan,
        effective_sticky_fn=lambda _: list(effective_sticky),
        run_state=KeepaliveRunState(data_dir=state_dir),
    )


# ── U1: happy path ─────────────────────────────────────────────────────────────


def test_happy_path_one_gap_published_alive(state_dir):
    seeds = [{"target_url": "https://target.example.com/page", "platform": "blogger"}]

    def _publish(seed):
        return {
            "target_url": seed["target_url"], "platform": seed["platform"],
            "published_url": "https://blogger.com/post/abc", "status": "published", "error": None,
        }

    def _reverify(result):
        return {"verdict": "alive"}

    result = _run(
        state_dir=state_dir, seeds=seeds, publish_fn=_publish, reverify_fn=_reverify,
    )
    assert result["gaps_found"] == 1
    assert result["published"] == 1
    assert result["reverified_alive"] == 1
    assert result["reverified_dead"] == 0


def test_dry_run_no_publish(state_dir):
    seeds = [{"target_url": "https://target.example.com/page", "platform": "blogger"}]
    publish_called = []

    def _publish(seed):
        publish_called.append(seed)
        return {"status": "published", "published_url": "https://x.com/p"}

    result = _run(state_dir=state_dir, seeds=seeds, publish_fn=_publish, dry_run=True)
    assert result.get("dry_run") is True
    assert not publish_called
    # dry_run exits before update_cycle_summary
    rs = KeepaliveRunState(data_dir=state_dir)
    assert rs.load()["last_run_at"] is None


def test_empty_recheck_no_gaps(state_dir):
    result = _run(state_dir=state_dir, seeds=[])
    assert result["gaps_found"] == 0
    assert result["published"] == 0


def test_probe_error_only_not_a_gap(state_dir):
    candidates = [{"live_url": "https://x.com/p", "target_url": "https://t.com",
                   "host": "x.com", "platform": "blogger"}]
    result = _run(state_dir=state_dir, candidates=candidates, probe_fn=_noop_probe, seeds=[])
    assert result["gaps_found"] == 0


def test_three_gap_integration_candidates_combined(state_dir):
    confirmed = [{"live_url": "https://x1.com/p", "target_url": "https://t1.com",
                  "host": "x1.com", "platform": "blogger"}]
    unverified = [{"live_url": "https://x2.com/p", "target_url": "https://t2.com",
                   "host": "x2.com", "platform": "blogger"}]
    probed = []

    def _probe(record):
        probed.append(record)
        return {**record, "verdict": "alive"}

    _run(state_dir=state_dir, candidates=confirmed, unverified=unverified,
         probe_fn=_probe, seeds=[])
    assert len(probed) == 2  # both confirmed and unverified probed


def test_cycle_lock_second_invocation_skipped(state_dir):
    import fcntl
    lock_path = state_dir / ".keepalive-run.lock"
    lock_path.touch()
    handle = open(str(lock_path), "w")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        result = _run(state_dir=state_dir, seeds=[])
        assert result.get("skipped") is True
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


# ── U2: weight gate ────────────────────────────────────────────────────────────


def test_effective_sticky_no_opt_state_fallback_to_full(tmp_path):
    from backlink_publisher.optimization.state import OptimizationState
    opt = OptimizationState(data_dir=tmp_path)  # no state file → default 1.0
    result = _effective_sticky(("blogger",), opt_state=opt)
    assert "blogger" in result


def test_effective_sticky_blogger_weight_zero(tmp_path):
    from backlink_publisher.optimization.state import OptimizationState
    opt = OptimizationState(data_dir=tmp_path)
    opt.set_weight("blogger", 0.0, rule="test", reason="circuit break test for U2 keepalive gate")
    result = _effective_sticky(("blogger",), opt_state=opt)
    assert result == []


def test_effective_sticky_blogger_weight_reduced_still_included(tmp_path):
    from backlink_publisher.optimization.state import OptimizationState
    opt = OptimizationState(data_dir=tmp_path)
    opt.set_weight("blogger", 0.3, rule="test", reason="reduced weight still > 0, not circuit broken")
    result = _effective_sticky(("blogger",), opt_state=opt)
    assert "blogger" in result


def test_effective_sticky_blogger_normal_weight(tmp_path):
    from backlink_publisher.optimization.state import OptimizationState
    opt = OptimizationState(data_dir=tmp_path)
    opt.set_weight("blogger", 1.0, rule="test", reason="normal weight baseline test")
    result = _effective_sticky(("blogger",), opt_state=opt)
    assert "blogger" in result


def test_all_platforms_circuit_broken_exits_cleanly(state_dir):
    result = _run(state_dir=state_dir, seeds=[], effective_sticky=())
    assert result["gaps_found"] == 0
    assert "skipped" not in result


# ── U3: reverify stat feedback ─────────────────────────────────────────────────


def test_reverify_alive_updates_opt_stats(tmp_path):
    from backlink_publisher.optimization.state import OptimizationState
    opt = OptimizationState(data_dir=tmp_path)
    _update_opt_stats("blogger", "alive", opt_state=opt)
    stats = opt.load()["stats"]["blogger"]
    assert stats["alive_count"] == 1
    assert stats["dofollow_count"] == 1


def test_reverify_dofollow_lost_increments_alive_not_dofollow(tmp_path):
    from backlink_publisher.optimization.state import OptimizationState
    opt = OptimizationState(data_dir=tmp_path)
    _update_opt_stats("blogger", "dofollow_lost", opt_state=opt)
    stats = opt.load()["stats"]["blogger"]
    assert stats["alive_count"] == 1
    assert stats["dofollow_count"] == 0


def test_reverify_probe_error_no_stat_change(tmp_path):
    from backlink_publisher.optimization.state import OptimizationState
    opt = OptimizationState(data_dir=tmp_path)
    _update_opt_stats("blogger", "probe_error", opt_state=opt)
    data = opt.load()
    assert "blogger" not in data.get("stats", {})


def test_reverify_link_stripped_no_stat_increment(tmp_path):
    from backlink_publisher.optimization.state import OptimizationState
    opt = OptimizationState(data_dir=tmp_path)
    _update_opt_stats("blogger", "link_stripped", opt_state=opt)
    data = opt.load()
    assert "blogger" not in data.get("stats", {})


def test_reverify_stat_rmw_increments_not_overwrites(tmp_path):
    from backlink_publisher.optimization.state import OptimizationState
    opt = OptimizationState(data_dir=tmp_path)
    opt.update_stats("blogger", {
        "alive_count": 10, "dofollow_count": 8, "total_published": 15, "drift_count": 2
    })
    _update_opt_stats("blogger", "alive", opt_state=opt)
    stats = opt.load()["stats"]["blogger"]
    assert stats["alive_count"] == 11   # RMW incremented, not reset to 1
    assert stats["dofollow_count"] == 9
    assert stats["total_published"] == 15  # untouched


def test_reverify_stat_new_platform_gets_defaults(tmp_path):
    from backlink_publisher.optimization.state import OptimizationState
    opt = OptimizationState(data_dir=tmp_path)
    _update_opt_stats("mataroa", "alive", opt_state=opt)
    stats = opt.load()["stats"]["mataroa"]
    assert stats["alive_count"] == 1
    assert "dofollow_count" in stats


def test_reverify_dead_records_attempt_in_run_state(state_dir):
    seeds = [{"target_url": "https://target.example.com/page", "platform": "blogger"}]

    def _publish(seed):
        return {
            "target_url": seed["target_url"], "platform": seed["platform"],
            "published_url": "https://blogger.com/post/dead", "status": "published", "error": None,
        }

    def _reverify(result):
        return {"verdict": "link_stripped"}

    result = _run(state_dir=state_dir, seeds=seeds, publish_fn=_publish, reverify_fn=_reverify)
    assert result["reverified_dead"] == 1
    rs = KeepaliveRunState(data_dir=state_dir)
    assert rs.load()["retry_counts"]["https://target.example.com/page"]["attempts"] == 1


def test_exhausted_target_skipped(state_dir):
    target = "https://exhausted.example.com/page"
    rs = KeepaliveRunState(data_dir=state_dir)
    for _ in range(3):
        rs.record_attempt(target, "blogger", "reverify_dead")

    seeds = [{"target_url": target, "platform": "blogger"}]
    publish_called = []

    def _publish(seed):
        publish_called.append(seed)
        return {"status": "published", "published_url": "https://x.com",
                "target_url": seed["target_url"], "platform": seed["platform"]}

    result = _run(state_dir=state_dir, seeds=seeds, publish_fn=_publish)
    assert not publish_called
    assert result["exhausted_skipped"] == 1


def test_probe_error_reverify_no_attempt_increment(state_dir):
    seeds = [{"target_url": "https://target.example.com/page", "platform": "blogger"}]

    def _publish(seed):
        return {
            "target_url": seed["target_url"], "platform": seed["platform"],
            "published_url": "https://blogger.com/post/x", "status": "published", "error": None,
        }

    def _reverify(result):
        return {"verdict": "probe_error"}

    result = _run(state_dir=state_dir, seeds=seeds, publish_fn=_publish, reverify_fn=_reverify)
    assert result["reverified_error"] == 1
    rs = KeepaliveRunState(data_dir=state_dir)
    assert not rs.is_exhausted("https://target.example.com/page")
