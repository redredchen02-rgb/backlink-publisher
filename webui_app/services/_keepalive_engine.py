"""Keep-alive engine helpers: candidates, probes, dataclasses, per-site runner.

Extracted from ``keepalive_job.py`` (Wave 3 Unit 4, 2026-06-11).
``keepalive_job.py`` re-exports all public names for backward compatibility.

``_default_reverify`` / ``_ensure_article`` / ``recheck_link`` stay in
``keepalive_job.py`` because tests patch ``keepalive_job.recheck_link`` and
call those helpers directly from ``keepalive_job``.

Tests that exercise ``run_keepalive_for_site`` must patch names in THIS
module (``webui_app.services._keepalive_engine.*``), not in keepalive_job.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import threading
from typing import Any

from backlink_publisher.events import EventStore
from backlink_publisher.keepalive.sticky import RUNTIME_STICKY_PLATFORMS
from backlink_publisher.recheck import selection
from backlink_publisher.recheck.events_io import emit_recheck, write_verified_at
from backlink_publisher.recheck.probe import recheck_link

# ── Constants ────────────────────────────────────────────────────────────────

#: ghpages is sticky by design but unusable while the GitHub account is
#: suspended, so the runtime republish default is blogger-only. The engine
#: constant stays {blogger, ghpages}; the job narrows it. Public alias so the
#: scorecard view derives the SAME gap set the job will publish (no S2↔S3 drift).
#: Single source of truth is backlink_publisher.keepalive.sticky (core) so
#: keepalive/chain.py reads it without importing webui_app; _RUNTIME_STICKY
#: aliases the imported value to keep this module's existing internal name.
_RUNTIME_STICKY = RUNTIME_STICKY_PLATFORMS

#: A worker exception or a probe that raises is recorded as this verdict —
#: "check-failed", never a gap (R1-a; the gap engine excludes probe_error).
_PROBE_ERROR = "probe_error"

#: Verdicts that mean a freshly-published link was eaten immediately → S7
#: treadmill. Mirrors ``gap.engine._DEAD_VERDICTS`` (same death taxonomy);
#: ``probe_error`` is deliberately NOT here (indeterminate, never a re-strip).
_DEAD_VERDICTS = ("link_stripped", "host_gone")


# ── Default candidate / probe helpers ────────────────────────────────────────


def _default_candidates(store: EventStore) -> list[dict]:
    return selection.select_candidates(store, now=datetime.now())


def _default_unverified_candidates(store: EventStore) -> list[dict]:
    return selection.select_unverified_candidates(store, now=datetime.now())


def _default_probe(record: dict) -> dict:
    return recheck_link(record, probe=True)


# ── Job dataclasses ───────────────────────────────────────────────────────────


@dataclass
class KeepaliveJob:
    id: str
    kind: str                                   # "recheck"
    status: str                                 # running|done|cancelled|error
    started_at: str
    total: int = 0
    checked: int = 0
    verdict_counts: dict[str, int] = field(default_factory=dict)
    per_host: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    cancel_requested: bool = False


@dataclass
class GapClosureJob:
    id: str
    kind: str  # "gap_closure"
    status: str  # running|done|error
    started_at: str
    output: str = ""
    error: str | None = None


@dataclass
class RepublishJob:
    id: str
    kind: str  # "republish"
    status: str  # running|done|error
    started_at: str
    total: int = 0
    published: int = 0
    failed: int = 0
    results: list[dict] = field(default_factory=list)
    state: str = ""  # all_success | partial_success | all_failed | treadmill (S6 / S6-partial / S7)
    error: str | None = None
    # 7b auto-recheck phase: publishing (S5) → rechecking (S6 probe) → done.
    phase: str = "publishing"
    reverify_total: int = 0
    reverify_done: int = 0
    reverified: list[dict] = field(default_factory=list)  # {target_url, published_url, verdict}
    restripped: int = 0        # fresh URLs already stripped on the confirming recheck → S7
    confirmed_alive: int = 0   # fresh URLs proven live → S6


# ── Default publish/gap/persist helpers ──────────────────────────────────────


def _default_republish_gaps(store: EventStore) -> Any:
    """Re-derive the authoritative keep-alive gap set from fresh state.

    Server-side truth (D6): never trust posted gap ids. ghpages is dropped from
    the sticky set at runtime (GitHub suspended) → blogger-only seeds.
    """

    from backlink_publisher.gap.engine import GapOptions, plan_keepalive_gap
    from backlink_publisher.ledger import build_ledger
    from backlink_publisher.recheck.events_io import derive_per_target_status

    rows = build_ledger(store=store)
    status = derive_per_target_status(store)
    return plan_keepalive_gap(
        rows, status, GapOptions(desired=5, language="zh-CN"),
        sticky_platforms=_RUNTIME_STICKY,
    )


def _default_publish_seed(seed: dict) -> dict:
    """Plan → validate → publish one sticky seed (subprocess publish), returning a
    structured per-item result (never raises; a failure is a row, not an abort)."""
    import json as _json

    from backlink_publisher.sdk.api import parse_publish_results, PipelineAPI

    api = PipelineAPI()
    target, platform = seed.get("target_url"), seed.get("platform")
    base = {"target_url": target, "platform": platform, "published_url": "", "status": "failed", "error": None}
    plan_res = api.plan(_json.dumps(seed))
    if not plan_res.success:
        return {**base, "error": plan_res.error or "plan failed"}
    val_res = api.validate(plan_res.stdout)
    if not val_res.success:
        return {**base, "error": val_res.error or "validate failed"}
    # publish only the first generated variant — one new link per gap.
    one = (val_res.stdout or "").splitlines()
    assert platform is not None
    pub_res = api.publish((one[0] + "\n") if one else "", platform, "publish")
    rows = parse_publish_results(pub_res.stdout)
    row = rows[0] if rows else {}
    url = (row.get("published_url") or row.get("draft_url") or "").strip()
    if url:
        return {**base, "published_url": url, "status": "published", "error": None}
    return {**base, "error": (row.get("error") or pub_res.error or "publish failed")}


def _default_persist(entry: dict) -> None:
    """Persist a published-but-unverified history row BEFORE auto-recheck, so a
    crash between publish and recheck leaves a recoverable, honest record."""
    from webui_store import history_store
    history_store.update(lambda hist: [entry, *hist][:200])


# ── Per-site synchronous autopilot helper ─────────────────────────────────────


@dataclass
class KeepAliveResult:
    """Structured return value for ``run_keepalive_for_site``."""
    success: bool
    checked: int
    errors: int
    error: str | None = None


# Per-site non-reentrant locks (created on demand).
_SITE_LOCKS: dict[str, threading.Lock] = {}
_SITE_LOCKS_MU = threading.Lock()


def _site_lock(site_url: str) -> threading.Lock:
    with _SITE_LOCKS_MU:
        if site_url not in _SITE_LOCKS:
            _SITE_LOCKS[site_url] = threading.Lock()
        return _SITE_LOCKS[site_url]


def run_keepalive_for_site(site_url: str) -> KeepAliveResult:
    """Run a synchronous recheck cycle for one site only.

    (a) Acquires a per-site lock (non-blocking) so concurrent autopilot
        ticks for the same site are skipped rather than doubled.
    (b) Filters EventStore candidates to those whose ``target_url`` starts
        with the site domain, so the job touches only this site.
    (c) Runs the probe loop synchronously on the caller's thread — safe
        to call from an APScheduler worker thread.

    Returns a :class:`KeepAliveResult` and never raises — a crash in the
    probe loop is captured as ``success=False, error=...`` so the
    APScheduler thread stays alive.
    """
    from urllib.parse import urlsplit
    lock = _site_lock(site_url)
    if not lock.acquire(blocking=False):
        return KeepAliveResult(
            success=False, checked=0, errors=0,
            error=f"already running for {site_url}",
        )
    try:
        try:
            parsed = urlsplit(site_url)
            domain = (parsed.scheme or "") + "://" + (parsed.netloc or "")
        except Exception:
            domain = site_url.rstrip("/")

        store = EventStore()
        confirmed = _default_candidates(store)
        unverified = _default_unverified_candidates(store)
        candidates = [
            c for c in confirmed + unverified
            if (c.get("target_url") or "").startswith(domain)
        ]

        checked = 0
        errors = 0
        for cand in candidates:
            try:
                result = _default_probe(cand)
            except Exception as exc:  # noqa: BLE001
                result = {**cand, "verdict": _PROBE_ERROR, "reason": f"probe error: {exc}"}
                errors += 1
            try:
                emit_recheck(store, [result])
            except Exception:  # noqa: BLE001
                pass
            try:
                write_verified_at(store, [result])
            except Exception:  # noqa: BLE001
                pass
            checked += 1

        return KeepAliveResult(success=True, checked=checked, errors=errors)
    except Exception as exc:  # noqa: BLE001
        return KeepAliveResult(success=False, checked=0, errors=0, error=str(exc))
    finally:
        lock.release()
