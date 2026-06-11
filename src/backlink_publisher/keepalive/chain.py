"""Keep-alive recovery loop — five-step chain orchestrator (plan 2026-06-05-004).

Steps
-----
1. Recheck — probe confirmed + unverified candidates; write_verified_at on alive.
2. Status derivation — derive_per_target_status from events.db.
3. Gap planning — plan_keepalive_gap with weight-gated sticky platforms (U2).
4. Publish — PipelineAPI per seed; record history per row.
5. Reverify + stat feedback — probe newly published URLs; update optimization_state (U3).

All dependencies are injectable so the chain is fully testable without network.
"""
from __future__ import annotations

import contextlib
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: Per-probe timeout (mirrors recheck_backlinks._PER_TARGET_TIMEOUT).
_PER_TARGET_TIMEOUT = 10.0
#: Total wall-clock budget for the recheck step.
_BATCH_BUDGET_S = 600.0

_DEAD_VERDICTS = ("link_stripped", "host_gone")


# ── cycle-level file lock ──────────────────────────────────────────────────────


@contextlib.contextmanager
def _cycle_lock(config_dir: Path):
    """Non-blocking exclusive file lock for the entire recovery cycle.

    Yields True if acquired, False if another keepalive cycle is already running.
    """
    import fcntl

    config_dir.mkdir(parents=True, exist_ok=True)
    lock_path = config_dir / ".keepalive-run.lock"
    handle = open(lock_path, "w")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


# ── default dependency implementations ────────────────────────────────────────


def _default_select_candidates(store):
    from backlink_publisher.recheck import selection
    return selection.select_candidates(store, now=datetime.now())


def _default_select_unverified(store):
    from backlink_publisher.recheck import selection
    return selection.select_unverified_candidates(store, now=datetime.now())


def _default_probe(record: dict) -> dict:
    from backlink_publisher.recheck.probe import recheck_link
    return recheck_link(record, probe=True, timeout=_PER_TARGET_TIMEOUT)


def _default_derive_status(store):
    from backlink_publisher.recheck.events_io import derive_per_target_status
    return derive_per_target_status(store)


def _default_build_ledger(store):
    from backlink_publisher.ledger import build_ledger
    return build_ledger(store=store)


def _default_emit_recheck(store, results):
    from backlink_publisher.recheck.events_io import emit_recheck
    return emit_recheck(store, results)


def _default_write_verified_at(store, results):
    from backlink_publisher.recheck.events_io import write_verified_at
    return write_verified_at(store, results)


def _default_publish_seed(seed: dict) -> dict:
    """Plan → validate → publish one seed via PipelineAPI (same as keepalive_job)."""
    import json as _json
    from webui_app.api.pipeline_api import PipelineAPI, parse_publish_results

    api = PipelineAPI()
    target, platform = seed.get("target_url"), seed.get("platform")
    base = {
        "target_url": target, "platform": platform,
        "published_url": "", "status": "failed", "error": None,
    }
    plan_res = api.plan(_json.dumps(seed))
    if not plan_res.success:
        return {**base, "error": plan_res.error or "plan failed"}
    val_res = api.validate(plan_res.stdout)
    if not val_res.success:
        return {**base, "error": val_res.error or "validate failed"}
    one = (val_res.stdout or "").splitlines()
    pub_res = api.publish((one[0] + "\n") if one else "", platform, "publish")
    rows = parse_publish_results(pub_res.stdout)
    row = rows[0] if rows else {}
    url = (row.get("published_url") or row.get("draft_url") or "").strip()
    if url:
        return {**base, "published_url": url, "status": "published", "error": None}
    return {**base, "error": (row.get("error") or pub_res.error or "publish failed")}


def _default_reverify(result: dict, store) -> dict:
    """Probe a freshly published URL; emit + write_verified_at (same as keepalive_job)."""
    from urllib.parse import urlsplit
    from backlink_publisher.recheck.probe import recheck_link
    from backlink_publisher.recheck.events_io import emit_recheck, write_verified_at

    url = (result.get("published_url") or "").strip()
    target = result.get("target_url")
    platform = result.get("platform")
    record = {
        "live_url": url, "target_url": target,
        "host": (urlsplit(url).hostname or "").lower(), "platform": platform,
    }
    verdict = recheck_link(record, probe=True, timeout=_PER_TARGET_TIMEOUT)
    # Register article so the confirming recheck carries an article_id.
    try:
        from webui_app.services.keepalive_job import _ensure_article
        article_id = _ensure_article(
            store, live_url=url, target_url=target,
            host=record["host"], platform=platform,
        )
        if article_id is not None:
            verdict = {**verdict, "article_id": article_id}
    except Exception:  # noqa: BLE001
        pass
    try:
        emit_recheck(store, [verdict])
    except Exception:  # noqa: BLE001
        pass
    try:
        write_verified_at(store, [verdict])
    except Exception:  # noqa: BLE001
        pass
    return verdict


# ── U2: weight gate ───────────────────────────────────────────────────────────


def _effective_sticky(runtime_sticky: tuple[str, ...], opt_state=None) -> list[str]:
    """Filter sticky platforms to those not circuit-broken (weight > 0).

    Falls back to full runtime_sticky on any OptimizationState error.
    ``opt_state`` is injectable for tests; defaults to a fresh OptimizationState().
    """
    try:
        if opt_state is None:
            from backlink_publisher.optimization.state import OptimizationState
            opt_state = OptimizationState()
        filtered = [p for p in runtime_sticky if opt_state.get_weight(p, default=1.0) > 0.0]
        return filtered
    except Exception as exc:  # noqa: BLE001
        logger.warning("OptimizationState unavailable, using full sticky list: %s", exc)
        return list(runtime_sticky)


# ── U3: stat feedback ─────────────────────────────────────────────────────────


def _update_opt_stats(platform: str, verdict: str, opt_state=None, language: str = "default") -> None:
    """RMW-increment alive_count / dofollow_count in optimization_state.json.

    Uses explicit load-modify-save under state._lock — NOT update_stats() which
    does dict.update (key overwrite, would reset a platform's existing counts).
    ``opt_state`` is injectable for tests; defaults to a fresh OptimizationState().
    """
    if verdict == "probe_error":
        return  # indeterminate — never update stats
    if verdict not in ("alive", "dofollow_lost"):
        return  # link_stripped / host_gone → not a stat we increment here
    try:
        if opt_state is None:
            from backlink_publisher.optimization.state import OptimizationState
            opt_state = OptimizationState()
        with opt_state._lock:
            data = opt_state.load()
            lang_stats = data.setdefault("stats", {}).setdefault(language, {})
            entry = lang_stats.setdefault(platform, {
                "alive_count": 0, "dofollow_count": 0,
                "total_published": 0, "drift_count": 0,
            })
            if verdict in ("alive", "dofollow_lost"):
                entry["alive_count"] = entry.get("alive_count", 0) + 1
            if verdict == "alive":
                entry["dofollow_count"] = entry.get("dofollow_count", 0) + 1
            opt_state.save(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to update optimization stats for %s: %s", platform, exc)


# ── main chain ────────────────────────────────────────────────────────────────


class CycleSummary:
    """Mutable accumulator for cycle statistics."""

    def __init__(self) -> None:
        self.gaps_found = 0
        self.published = 0
        self.reverified_alive = 0
        self.reverified_dead = 0
        self.reverified_error = 0
        self.exhausted_skipped = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "gaps_found": self.gaps_found,
            "published": self.published,
            "reverified_alive": self.reverified_alive,
            "reverified_dead": self.reverified_dead,
            "reverified_error": self.reverified_error,
            "exhausted_skipped": self.exhausted_skipped,
        }


def run_cycle(
    *,
    store=None,
    dry_run: bool = False,
    max_gaps: int | None = None,
    min_age_days: int = 7,
    config_dir: Path | None = None,
    # injectable for tests
    select_candidates_fn: Callable | None = None,
    select_unverified_fn: Callable | None = None,
    probe_fn: Callable | None = None,
    derive_status_fn: Callable | None = None,
    build_ledger_fn: Callable | None = None,
    emit_recheck_fn: Callable | None = None,
    write_verified_at_fn: Callable | None = None,
    publish_fn: Callable | None = None,
    reverify_fn: Callable | None = None,
    plan_gap_fn: Callable | None = None,
    effective_sticky_fn: Callable | None = None,
    run_state=None,
) -> dict[str, Any]:
    """Run one keepalive recovery cycle.

    Returns a cycle_summary dict. Logs RECON-level events throughout.
    Acquires cycle-level lock; returns ``{"skipped": True}`` if already running.
    """
    from backlink_publisher._util.logger import get_logger
    from backlink_publisher.events import EventStore
    from backlink_publisher.gap.engine import GapOptions, plan_keepalive_gap
    from backlink_publisher.keepalive.run_state import KeepaliveRunState
    from webui_app.services.keepalive_job import RUNTIME_STICKY_PLATFORMS

    _log = get_logger("keepalive")

    store = store or EventStore()
    if config_dir is None:
        config_dir = store.path.parent

    run_state = run_state or KeepaliveRunState(data_dir=config_dir)

    # Resolve injectable dependencies
    _select = select_candidates_fn or _default_select_candidates
    _select_unv = select_unverified_fn or _default_select_unverified
    _probe = probe_fn or _default_probe
    _derive = derive_status_fn or _default_derive_status
    _ledger = build_ledger_fn or _default_build_ledger
    _emit = emit_recheck_fn or _default_emit_recheck
    _vat = write_verified_at_fn or _default_write_verified_at
    _publish = publish_fn or _default_publish_seed
    _reverify = reverify_fn or (lambda result: _default_reverify(result, store))
    _eff_sticky = effective_sticky_fn or _effective_sticky

    def _plan_gap(rows, per_target_status, opts, *, sticky_platforms=()):
        if plan_gap_fn is not None:
            return plan_gap_fn(rows, per_target_status, opts, sticky_platforms=sticky_platforms)
        return plan_keepalive_gap(rows, per_target_status, opts, sticky_platforms=sticky_platforms)

    summary = CycleSummary()

    # ── cycle-level lock ───────────────────────────────────────────────────
    with _cycle_lock(config_dir) as acquired:
        if not acquired:
            _log.recon("keepalive_cycle_skipped_locked")
            logger.info("keepalive: cycle already in progress, skipping")
            return {"skipped": True}

        # ── Step 1: Recheck ────────────────────────────────────────────────
        confirmed = _select(store)
        unverified = _select_unv(store)
        candidates = confirmed + unverified
        _log.recon("keepalive_recheck_start", candidates=len(candidates))

        results: list[dict] = []
        deadline = time.monotonic() + _BATCH_BUDGET_S
        for candidate in candidates:
            if time.monotonic() > deadline:
                logger.warning("keepalive: recheck batch budget exhausted, deferring remaining")
                break
            try:
                r = _probe(candidate)
            except Exception as exc:  # noqa: BLE001
                r = {**candidate, "verdict": "probe_error", "reason": f"probe error: {exc}"}
            results.append(r)
            try:
                _emit(store, [r])
            except Exception:  # noqa: BLE001
                logger.debug("emit_recheck failed", exc_info=True)
            try:
                _vat(store, [r])
            except Exception:  # noqa: BLE001
                logger.debug("write_verified_at failed", exc_info=True)

        _log.recon("keepalive_recheck_done", probed=len(results))

        # ── Step 2: Status derivation ──────────────────────────────────────
        per_target_status = _derive(store)

        # ── Step 3: Gap planning (U2: weight gate) ─────────────────────────
        effective = _eff_sticky(RUNTIME_STICKY_PLATFORMS)
        if not effective:
            _log.recon("keepalive_all_platforms_circuit_broken")
            logger.info("keepalive: all sticky platforms circuit-broken; no gaps to fill")
            summary_dict = summary.to_dict()
            run_state.update_cycle_summary(summary_dict)
            return summary_dict

        rows = _ledger(store)
        seeds_raw, gaps = _plan_gap(
            rows, per_target_status,
            GapOptions(desired=max_gaps or 10, language="zh-CN"),
            sticky_platforms=tuple(effective),
        )
        summary.gaps_found = len(seeds_raw)
        _log.recon("keepalive_gaps_found", gaps=summary.gaps_found, sticky=effective)

        if dry_run:
            _log.recon("keepalive_dry_run", gaps=summary.gaps_found)
            summary_dict = {**summary.to_dict(), "dry_run": True,
                            "seeds": seeds_raw}
            return summary_dict

        # Filter exhausted targets
        seeds = []
        for seed in seeds_raw:
            if run_state.is_exhausted(seed.get("target_url", "")):
                summary.exhausted_skipped += 1
            else:
                seeds.append(seed)

        if max_gaps is not None:
            seeds = seeds[:max_gaps]

        # ── Step 4: Publish ────────────────────────────────────────────────
        published_results: list[dict] = []
        for seed in seeds:
            try:
                result = _publish(seed)
            except Exception as exc:  # noqa: BLE001
                result = {
                    "target_url": seed.get("target_url"),
                    "platform": seed.get("platform"),
                    "published_url": "",
                    "status": "failed",
                    "error": f"publish error: {exc}",
                }
            ok = bool((result.get("published_url") or "").strip())
            if ok:
                summary.published += 1
            else:
                _t = result.get("target_url") or ""
                _p = result.get("platform") or ""
                if _t and _p:
                    run_state.record_attempt(_t, _p, "publish_failed")
            published_results.append(result)

        _log.recon("keepalive_publish_done",
                   published=summary.published, failed=len(seeds) - summary.published)

        # ── Step 5: Reverify + stat feedback (U3) ─────────────────────────
        for result in published_results:
            url = (result.get("published_url") or "").strip()
            if not url:
                continue
            platform = result.get("platform") or ""
            target_url = result.get("target_url") or ""
            try:
                verdict_dict = _reverify(result)
            except Exception as exc:  # noqa: BLE001
                verdict_dict = {"verdict": "probe_error", "reason": str(exc)}
            v = verdict_dict.get("verdict") or "probe_error"
            if v == "alive":
                summary.reverified_alive += 1
            elif v in _DEAD_VERDICTS:
                summary.reverified_dead += 1
                run_state.record_attempt(target_url, platform, v)
            else:
                summary.reverified_error += 1

            # U3: stat feedback — only for definitive verdicts
            if v != "probe_error" and platform:
                _update_opt_stats(platform, v)

        _log.recon(
            "keepalive_cycle_complete",
            gaps_found=summary.gaps_found,
            published=summary.published,
            reverified_alive=summary.reverified_alive,
            reverified_dead=summary.reverified_dead,
            exhausted_skipped=summary.exhausted_skipped,
        )

        summary_dict = summary.to_dict()
        run_state.update_cycle_summary(summary_dict)
        return summary_dict
