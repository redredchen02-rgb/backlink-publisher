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
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from backlink_publisher._util.errors import UsageError
from backlink_publisher.events import EventStore
from backlink_publisher.recheck import selection
from backlink_publisher.recheck.events_io import emit_recheck
from backlink_publisher.recheck.probe import recheck_link

#: A worker exception or a probe that raises is recorded as this verdict —
#: "check-failed", never a gap (R1-a; the gap engine excludes probe_error).
_PROBE_ERROR = "probe_error"


def _default_candidates(store: EventStore) -> list[dict]:
    return selection.select_candidates(store, now=datetime.now())


def _default_probe(record: dict) -> dict:
    return recheck_link(record, probe=True)


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


class KeepaliveJobRegistry:
    """In-memory keep-alive job registry (recheck today; republish in Unit 7)."""

    def __init__(self) -> None:
        self._jobs: dict[str, KeepaliveJob] = {}
        self._lock = threading.Lock()

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
                candidates = _default_candidates(store)
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

    def _poll_locked(self, job: KeepaliveJob) -> dict[str, Any]:
        return {
            "job_id": job.id,
            "kind": job.kind,
            "status": job.status,
            "started_at": job.started_at,
            "total": job.total,
            "checked": job.checked,
            "verdict_counts": dict(job.verdict_counts),
            "per_host": dict(job.per_host),
            "error": job.error,
        }

    def reset_for_tests(self) -> None:
        with self._lock:
            self._jobs.clear()


registry = KeepaliveJobRegistry()

__all__ = ["KeepaliveJob", "KeepaliveJobRegistry", "registry"]
