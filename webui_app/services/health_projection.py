"""WebUI adapter for the read-time projection backstop (Plan 2026-05-25-006 / U1).

Thin indirection over ``events.reconcile.project_on_read`` so routes and tests
can drive/mock the projection without reaching into the events package —
mirroring the other ``webui_app/services`` adapters.
"""

from __future__ import annotations

from typing import Any

from backlink_publisher.events.reconcile import ReadProjectionResult


def project_on_read() -> ReadProjectionResult:
    """Run the load-time projection backstop. Never raises (see reconcile)."""
    # Lazy import so ``unittest.mock.patch`` against
    # ``backlink_publisher.events.reconcile.project_on_read`` still takes effect
    # after this module has been imported.
    from backlink_publisher.events import reconcile

    return reconcile.project_on_read()


def compute_health_json() -> dict[str, Any]:
    """Return the /health payload (Plan 2026-06-09-001 U3; Sprint E3 added
    ``last_successful_pipeline_run``).

    503-triggering conditions: any channel expired/unreachable, scheduler not
    running, or last_pipeline_run is None.  All fields always present.
    ``last_successful_pipeline_run`` is informational only (does not affect
    ``healthy``/``degraded_reasons``) — it is ``None`` whenever there is no
    history yet, or every recorded run so far ended failed/unverified.
    """
    from webui_app.scheduler import _scheduler
    from webui_store import history_store
    from webui_store.channel_status import list_all as _list_all_channels

    # ── channel statuses ──────────────────────────────────────────────
    channels: dict[str, str] = {}
    try:
        raw = _list_all_channels()
        channels = {ch: rec.get("status", "unbound") for ch, rec in raw.items()}
    except Exception:  # noqa: BLE001
        pass

    # ── scheduler state ───────────────────────────────────────────────
    try:
        scheduler_running: bool = bool(_scheduler.running)
        scheduler_job_count: int = len(_scheduler.get_jobs())
    except Exception:  # noqa: BLE001
        scheduler_running = False
        scheduler_job_count = 0

    # ── last pipeline run (most recent created_at from history) ───────
    last_pipeline_run: str | None = None
    # ── last *successful* pipeline run (most recent "published" item) ──
    # Sprint E3: a lightweight timestamp-only signal, deliberately scoped
    # below full runtime-duration monitoring (which would need a new
    # start/end write-path threaded through the whole pipeline — out of
    # scope here; see plan doc E3 notes). "Successful" mirrors
    # health_metrics.py's honesty rule: only an unambiguous "published"
    # status counts, not "failed" or a "*_unverified" post-publish state.
    last_successful_pipeline_run: str | None = None
    try:
        items = history_store.load()
        if items:
            ts = max(
                (it.get("created_at") or "" for it in items if isinstance(it, dict)),
                default="",
            )
            last_pipeline_run = ts or None
            successful_ts = [
                it.get("created_at") or ""
                for it in items
                if isinstance(it, dict) and it.get("status") == "published"
            ]
            if successful_ts:
                last_successful_pipeline_run = max(successful_ts) or None
    except Exception:  # noqa: BLE001
        pass

    # ── degraded reasons ──────────────────────────────────────────────
    degraded_reasons: list[str] = []
    for ch, st in channels.items():
        if st in ("expired", "unreachable"):
            degraded_reasons.append(f"channel:{ch}:{st}")
    if not scheduler_running:
        degraded_reasons.append("scheduler:not_running")
    if last_pipeline_run is None:
        degraded_reasons.append("pipeline:never_run")

    healthy = len(degraded_reasons) == 0

    return {
        "healthy": healthy,
        "webui": "ok",
        "last_pipeline_run": last_pipeline_run,
        "last_successful_pipeline_run": last_successful_pipeline_run,
        "scheduler_running": scheduler_running,
        "scheduler_job_count": scheduler_job_count,
        "channels": channels,
        "degraded_reasons": degraded_reasons,
    }
