"""Keep-alive async job registry (plan 2026-06-04-001 Unit 5 / R1).

Mirrors :class:`bind_job.BindJobRegistry`'s structure — a lock, an in-memory
job dict, ``poll(job_id)``, and a one-running-job-per-kind conflict — but the
worker body is **net-new**: instead of ``Popen``-ing a CLI and draining stdout,
the recheck job runs the liveness probe **in-process on a worker thread** and
appends one append-only ``link.rechecked`` event per result. Append-only (never
a read-modify-write of a shared row) is what keeps it safe against the
concurrent APScheduler publish-queue writer (cross-process lost-update).

Concurrency: at most one running recheck job; a second ``start_recheck`` raises
:class:`UsageError` (the route maps it to 409). Job ids are ``uuid4().hex`` and
the poll surface returns only progress/rollups — never credentials or the full
target inventory.

Leave-and-return: G5a (rehydrate a *running* job on tab-reopen within the same
process) is free via ``poll(job_id)``. G5b (surviving a process restart) is
deferred — the durable ``events.db`` scorecard re-renders and an interrupted
recheck is simply re-run (recheck is idempotent / operator-triggered).

Wave 3 Unit 4 (2026-06-11): engine helpers, dataclasses, and per-site runner
extracted to ``_keepalive_engine.py``. This module keeps ``KeepaliveJobRegistry``
+ ``registry`` + the two helpers whose tests patch ``keepalive_job.recheck_link``
(``_default_reverify``, ``_ensure_article``).
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from backlink_publisher._util.errors import UsageError
from backlink_publisher.events import EventStore
from backlink_publisher.events._project_helpers import (  # noqa: F401 — re-exported; core home is events._project_helpers
    _ensure_article,
)
from backlink_publisher.recheck.events_io import emit_recheck, write_verified_at
from backlink_publisher.recheck.probe import recheck_link

from ._keepalive_engine import (  # noqa: F401 — re-exported for backward compat
    GapClosureJob,
    KeepAliveResult,
    KeepaliveJob,
    RepublishJob,
    RUNTIME_STICKY_PLATFORMS,
    _DEAD_VERDICTS,
    _PROBE_ERROR,
    _RUNTIME_STICKY,
    _default_candidates,
    _default_persist,
    _default_probe,
    _default_publish_seed,
    _default_republish_gaps,
    _default_unverified_candidates,
    _site_lock,
    run_keepalive_for_site,
)


# ── Helpers that stay here (tests patch keepalive_job.recheck_link) ───────────
# NOTE: _ensure_article moved to backlink_publisher.events._project_helpers
# (core home) and is re-exported above; tests call keepalive_job._ensure_article
# directly, which resolves via that re-export.


def _default_reverify(result: dict, store: EventStore) -> dict:
    """7b: probe ONE freshly-published article URL to prove the new backlink went
    live, and append the verdict to the ``link.rechecked`` series so the scorecard
    reflects it. ``link_stripped``/``host_gone`` here means the new URL was eaten
    immediately → S7 treadmill. Never raises; a probe failure is ``probe_error``."""
    from urllib.parse import urlsplit

    url = (result.get("published_url") or "").strip()
    target = result.get("target_url")
    platform = result.get("platform")
    record = {
        "live_url": url,
        "target_url": target,
        "host": (urlsplit(url).hostname or "").lower(),
        "platform": platform,
    }
    verdict = recheck_link(record, probe=True)
    # Register the new link as a tracked article so its confirming verdict carries
    # a real article_id (the verdict already carries target_url + platform) and
    # reaches the scorecard / net-coverage gap — an article_id-less recheck is
    # silently dropped by derive_per_target_status.
    article_id = _ensure_article(
        store, live_url=url, target_url=target, host=record["host"], platform=platform
    )
    if article_id is not None:
        verdict = {**verdict, "article_id": article_id}
    try:
        emit_recheck(store, [verdict])
    except Exception:  # noqa: BLE001 — a write failure must not lose the verdict signal
        pass
    # Mirror the regular recheck job: update articles.verified_at so the ledger
    # reflects the new alive link on the next build_ledger call. Without this,
    # liveness stays "unverified" and the link never enters live_dofollow_platforms
    # until the next scheduled recheck job runs write_verified_at itself.
    try:
        write_verified_at(store, [verdict])
    except Exception:  # noqa: BLE001
        pass
    return verdict


# ── Job registry ──────────────────────────────────────────────────────────────


class KeepaliveJobRegistry:
    """In-memory keep-alive job registry (recheck today; republish in Unit 7)."""

    def __init__(self) -> None:
        self._jobs: dict[str, Any] = {}
        self._lock = threading.Lock()
        # confirm nonce → gap-set fingerprint it was issued for (single-use).
        self._confirm_nonces: dict[str, str] = {}

    # ── recheck (Unit 5) ────────────────────────────────────────────────────
    def start_recheck(
        self,
        *,
        store: EventStore | None = None,
        candidates: list[dict] | None = None,
        probe_fn: Callable[[dict], dict] | None = None,
    ) -> KeepaliveJob:
        """Spawn a background recheck over ``candidates`` (default: the due set).

        ``store`` / ``candidates`` / ``probe_fn`` are injectable for tests so the
        job runs with no real network. Raises :class:`UsageError` if a recheck
        is already running.
        """
        store = store or EventStore()
        probe_fn = probe_fn or _default_probe
        with self._lock:
            for job in self._jobs.values():
                if job.kind == "recheck" and job.status == "running":
                    raise UsageError(
                        f"keepalive: a recheck job is already running ({job.id})"
                    )
            job_id = uuid.uuid4().hex
            job = KeepaliveJob(
                id=job_id,
                kind="recheck",
                status="running",
                started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            self._jobs[job_id] = job

        worker = threading.Thread(
            target=self._run_recheck,
            args=(job, store, candidates, probe_fn),
            daemon=True,
            name=f"keepalive-recheck-{job_id[:8]}",
        )
        worker.start()
        return job

    def _run_recheck(
        self,
        job: KeepaliveJob,
        store: EventStore,
        candidates: list[dict] | None,
        probe_fn: Callable[[dict], dict],
    ) -> None:
        try:
            if candidates is None:
                confirmed = _default_candidates(store)
                unverified = _default_unverified_candidates(store)
                candidates = confirmed + unverified
            with self._lock:
                job.total = len(candidates)

            for cand in candidates:
                with self._lock:
                    if job.cancel_requested:
                        job.status = "cancelled"
                        return
                try:
                    result = probe_fn(cand)
                except Exception as exc:  # noqa: BLE001 — a bad link never aborts the batch
                    result = {**cand, "verdict": _PROBE_ERROR, "reason": f"probe error: {exc}"}
                # Append-only: one link.rechecked event per result. A write
                # failure must not crash the worker or lose progress.
                try:
                    emit_recheck(store, [result])
                except Exception:  # noqa: BLE001
                    pass
                try:
                    write_verified_at(store, [result])
                except Exception:  # noqa: BLE001
                    pass
                with self._lock:
                    job.checked += 1
                    verdict = result.get("verdict") or _PROBE_ERROR
                    job.verdict_counts[verdict] = job.verdict_counts.get(verdict, 0) + 1
                    host = cand.get("host") or "?"
                    job.per_host[host] = job.per_host.get(host, 0) + 1

            with self._lock:
                if job.status == "running":
                    job.status = "done"
        except Exception as exc:  # noqa: BLE001 — surface, never hang
            with self._lock:
                job.status = "error"
                job.error = f"recheck job failed: {exc}"

    # ── gap_closure (full pipeline trigger) ────────────────────────────────
    def start_gap_closure(self) -> GapClosureJob:
        """Spawn a background full-pipeline gap-closure run.

        Runs ``run-full-pipeline.sh`` with the default gap options
        (equity → plan-gap → plan → validate → publish). Only one
        gap_closure job allowed at a time.
        """
        import subprocess
        from pathlib import Path

        with self._lock:
            for job in self._jobs.values():
                if job.kind == "gap_closure" and job.status == "running":
                    raise UsageError(
                        f"gap_closure: a job is already running ({job.id})"
                    )
            job_id = uuid.uuid4().hex
            job = GapClosureJob(
                id=job_id,
                kind="gap_closure",
                status="running",
                started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            self._jobs[job_id] = job

        repo_root = Path(__file__).resolve().parents[3]

        def _run():
            try:
                env = dict(os.environ, BP_DRY_RUN="0")
                proc = subprocess.run(
                    ["bash", "scripts/run-full-pipeline.sh"],
                    cwd=str(repo_root),
                    capture_output=True, text=True, timeout=7200,
                    env=env,
                )
                combined = proc.stdout or ""
                if proc.stderr:
                    combined += "\n--- stderr ---\n" + (proc.stderr or "")
                with self._lock:
                    job.output = combined
                    if proc.returncode != 0:
                        job.status = "error"
                        job.error = f"pipeline exited {proc.returncode}"
                    else:
                        job.status = "done"
            except subprocess.TimeoutExpired:
                with self._lock:
                    job.status = "error"
                    job.error = "pipeline timed out (2h limit)"
            except Exception as exc:
                with self._lock:
                    job.status = "error"
                    job.error = f"gap_closure failed: {exc}"

        import os
        import threading
        worker = threading.Thread(target=_run, daemon=True,
                                  name=f"gap-closure-{job_id[:8]}")
        worker.start()
        return job

    # ── poll / cancel ───────────────────────────────────────────────────────
    def cancel(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status == "running":
                job.cancel_requested = True
            return self._poll_locked(job)

    def poll(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return self._poll_locked(job)

    def running_job(self, kind: str = "recheck") -> dict[str, Any] | None:
        """The currently-running job of ``kind`` (for tab-reopen rehydrate, G5a)."""
        with self._lock:
            for job in self._jobs.values():
                if job.kind == kind and job.status == "running":
                    return self._poll_locked(job)
            return None

    def _poll_locked(self, job: Any) -> dict[str, Any]:
        base = {
            "job_id": job.id,
            "kind": job.kind,
            "status": job.status,
            "started_at": job.started_at,
            "total": job.total,
            "error": job.error,
        }
        if job.kind == "gap_closure":
            base.update({
                "output": job.output,
            })
        elif job.kind == "republish":
            base.update({
                "published": job.published,
                "failed": job.failed,
                "results": list(job.results),
                "state": job.state,
                "phase": job.phase,
                "reverify_total": job.reverify_total,
                "reverify_done": job.reverify_done,
                "reverified": list(job.reverified),
                "restripped": job.restripped,
                "confirmed_alive": job.confirmed_alive,
            })
        else:
            base.update({
                "checked": job.checked,
                "verdict_counts": dict(job.verdict_counts),
                "per_host": dict(job.per_host),
            })
        return base

    # ── republish (Unit 7) ──────────────────────────────────────────────────
    @staticmethod
    def _gap_fingerprint(seeds: list[dict]) -> str:
        key = sorted((s.get("target_url", ""), s.get("platform", "")) for s in seeds)
        return hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16]

    def issue_confirm_token(self, *, store: EventStore | None = None, gap_fn=None) -> dict[str, Any]:
        """Issue a single-use confirm nonce bound to the CURRENT gap set.

        The nonce doubles as the anti-stale / anti-double-submit guard: if the
        gap set changes before confirm (a link went live), the stale nonce no
        longer matches the re-derived fingerprint and the republish is rejected.
        """
        store = store or EventStore()
        gap_fn = gap_fn or _default_republish_gaps
        seeds, gaps = gap_fn(store)
        fingerprint = self._gap_fingerprint(seeds)
        token = uuid.uuid4().hex
        with self._lock:
            self._confirm_nonces[token] = fingerprint
        return {
            "confirm_token": token,
            "gap_fingerprint": fingerprint,
            "targets": sorted({s.get("target_url") for s in seeds}),
            "seed_count": len(seeds),
            # per-seed destinations so the S4 confirm modal can line-item each
            # republish as "<target deep page> → <sticky platform>" (the exact
            # server-side plan, not a client guess).
            "seeds": [
                {"target_url": s.get("target_url"), "platform": s.get("platform")}
                for s in seeds
            ],
        }

    def start_republish(
        self,
        *,
        selected_targets: list[str],
        confirm_token: str,
        store: EventStore | None = None,
        gap_fn=None,
        publish_fn: Callable[[dict], dict] | None = None,
        persist_fn: Callable[[dict], None] | None = None,
        recheck_fn: Callable[[dict], dict] | None = None,
        sticky_platforms=_RUNTIME_STICKY,
    ) -> RepublishJob:
        """Republish the selected stripped-link gaps to sticky platforms.

        Security: re-derives the gap set from fresh state (never trusts the
        posted ids), drops any seed outside ``sticky_platforms``, and consumes a
        single-use confirm nonce bound to the current gap fingerprint. Raises
        :class:`UsageError` on a bad/stale nonce, a non-sticky destination, or a
        second concurrent republish.
        """
        store = store or EventStore()
        gap_fn = gap_fn or _default_republish_gaps
        publish_fn = publish_fn or _default_publish_seed
        persist_fn = persist_fn or _default_persist
        recheck_fn = recheck_fn or (lambda result: _default_reverify(result, store))
        sticky = set(sticky_platforms)
        wanted = set(selected_targets or [])

        seeds, _gaps = gap_fn(store)
        fingerprint = self._gap_fingerprint(seeds)

        # Re-derive the plan from server truth (pure, no shared state): only seeds
        # that are STILL a gap AND were selected AND are sticky survive (a now-live
        # or forged target is dropped here). Done before the lock — local-only.
        non_sticky = [s for s in seeds if s.get("platform") not in sticky]
        if non_sticky:
            # Defense in depth: the engine should never emit a non-sticky seed.
            raise UsageError("keepalive: refusing a non-sticky republish destination")
        plan = [
            s for s in seeds
            if s.get("target_url") in wanted and s.get("platform") in sticky
        ]

        # ONE atomic lock block (mirror start_recheck): conflict-check → consume
        # nonce → insert running job. A split (check in one block, insert in
        # another) is a TOCTOU — two concurrent calls with two distinct valid
        # tokens could both pass the check and both start a worker → double-publish.
        with self._lock:
            for job in self._jobs.values():
                if job.kind == "republish" and job.status == "running":
                    raise UsageError(f"keepalive: a republish job is already running ({job.id})")
            # single-use nonce, bound to the freshly re-derived gap set. The
            # running-job check above is FIRST so a conflict doesn't burn the nonce.
            issued_for = self._confirm_nonces.pop(confirm_token, None)
            if issued_for is None:
                raise UsageError("keepalive: invalid or already-used confirm token")
            if issued_for != fingerprint:
                raise UsageError("keepalive: gap set changed since confirm — re-run the recheck")
            job_id = uuid.uuid4().hex
            job = RepublishJob(
                id=job_id, kind="republish", status="running",
                started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                total=len(plan),
            )
            self._jobs[job_id] = job

        worker = threading.Thread(
            target=self._run_republish, args=(job, plan, publish_fn, persist_fn, recheck_fn),
            daemon=True, name=f"keepalive-republish-{job_id[:8]}",
        )
        worker.start()
        return job

    def _run_republish(self, job, plan, publish_fn, persist_fn, recheck_fn):
        try:
            # ── publish phase (S5) ──────────────────────────────────────────
            for seed in plan:
                try:
                    result = publish_fn(seed)
                except Exception as exc:  # noqa: BLE001
                    result = {
                        "target_url": seed.get("target_url"), "platform": seed.get("platform"),
                        "published_url": "", "status": "failed", "error": f"publish error: {exc}",
                    }
                ok = bool((result.get("published_url") or "").strip())
                if ok:
                    # persist-before-recheck: a recoverable record even on crash.
                    try:
                        persist_fn({
                            "id": uuid.uuid4().hex,
                            "status": "published_unverified",
                            "platform": result.get("platform"),
                            "target_url": result.get("target_url"),
                            "article_urls": [result["published_url"]],
                            "verified_at": None,
                        })
                    except Exception:  # noqa: BLE001
                        pass
                with self._lock:
                    job.results.append(result)
                    if ok:
                        job.published += 1
                    else:
                        job.failed += 1

            # ── auto-recheck phase (7b / S6): prove the new URLs went live, or
            # terminate in S7 (treadmill) if a fresh URL was eaten immediately.
            # No auto-loop (D5) — one confirming recheck, then a terminal verdict.
            with self._lock:
                job.phase = "rechecking"
                ok_results = [r for r in job.results if (r.get("published_url") or "").strip()]
                job.reverify_total = len(ok_results)
            for res in ok_results:
                try:
                    verdict = recheck_fn(res)
                except Exception as exc:  # noqa: BLE001
                    verdict = {"verdict": _PROBE_ERROR, "reason": f"reverify error: {exc}"}
                v = verdict.get("verdict") or _PROBE_ERROR
                with self._lock:
                    job.reverify_done += 1
                    job.reverified.append({
                        "target_url": res.get("target_url"),
                        "published_url": res.get("published_url"),
                        "verdict": v,
                    })
                    if v in _DEAD_VERDICTS:
                        job.restripped += 1
                    elif v == "alive":
                        job.confirmed_alive += 1

            with self._lock:
                job.state = self._republish_state(job)
                job.phase = "done"
                job.status = "done"
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                job.status = "error"
                job.error = f"republish job failed: {exc}"

    @staticmethod
    def _republish_state(job) -> str:
        """Map publish + auto-recheck outcome to a terminal state (G1: no raw
        codes). A fresh URL re-stripped (S7) outranks any publish partial — it's
        the strongest signal that the destination is unreliable (D5)."""
        if job.restripped > 0:
            return "treadmill"          # S7
        if job.published == 0:
            return "all_failed"
        if job.failed == 0:
            return "all_success"        # S6
        return "partial_success"        # S6-partial

    def reset_for_tests(self) -> None:
        with self._lock:
            self._jobs.clear()
            self._confirm_nonces.clear()


registry = KeepaliveJobRegistry()


__all__ = [
    "KeepaliveJob", "RepublishJob", "KeepaliveJobRegistry", "registry",
    "KeepAliveResult", "run_keepalive_for_site",
    "RUNTIME_STICKY_PLATFORMS",
]
