"""WebUI adapter for the read-time projection backstop (Plan 2026-05-25-006 / U1).

Thin indirection over ``events.reconcile.project_on_read`` so routes and tests
can drive/mock the projection without reaching into the events package —
mirroring the other ``webui_app/services`` adapters.
"""

from __future__ import annotations

from typing import Any

from backlink_publisher.events.reconcile import ReadProjectionResult

# Identifier for the "never published yet" neutral state (Plan
# 2026-07-06-005 W15 / D13). Kept as a module-level string (rather than only
# a bare bool) so any consumer — including the legacy static/js health bar,
# which still greps for this exact literal (see
# tests/test_webui_feedback_states.py::test_health_bar_never_run_literal_matches_backend)
# — has one canonical spelling to key off of. It intentionally never enters
# ``degraded_reasons``; see ``never_run``/``never_run_reason`` in the
# ``compute_health_json`` payload.
_NEVER_RUN_REASON = "pipeline:never_run"


def project_on_read() -> ReadProjectionResult:
    """Run the load-time projection backstop. Never raises (see reconcile)."""
    # Lazy import so ``unittest.mock.patch`` against
    # ``backlink_publisher.events.reconcile.project_on_read`` still takes effect
    # after this module has been imported.
    from backlink_publisher.events import reconcile

    return reconcile.project_on_read()


def compute_health_json() -> dict[str, Any]:
    """Return the /health payload (Plan 2026-06-09-001 U3; Sprint E3 added
    ``last_successful_pipeline_run``; Plan 2026-07-06-005 W15 / D13 split out
    ``never_run``).

    503-triggering conditions: any channel expired/unreachable, or scheduler
    not running. All fields always present. A brand-new install that has
    never published (``last_pipeline_run is None``) is a neutral third state,
    not a degraded one: it never contributes to ``degraded_reasons`` and
    never fails the ``healthy`` check on its own. It is surfaced only via the
    dedicated ``never_run`` boolean. If ``never_run`` coincides with a *real*
    failure (a channel down, the scheduler stopped), that real reason still
    lands in ``degraded_reasons`` and ``healthy`` is still ``False`` —
    never_run only exempts "nothing has run yet", it never masks an actual
    fault (D13).
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
    except Exception:
        pass

    # ── scheduler state ───────────────────────────────────────────────
    try:
        scheduler_running: bool = bool(_scheduler.running)
        scheduler_job_count: int = len(_scheduler.get_jobs())
    except Exception:
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
    except Exception:
        pass

    # ── degraded reasons ──────────────────────────────────────────────
    # never_run is a neutral third state (D13): a fresh install that has
    # never published is NOT the same as a real failure, so it is tracked
    # separately and deliberately excluded from `degraded_reasons` — it must
    # never contribute to `healthy` being False on its own. Real failures
    # (channel down, scheduler stopped) still land in `degraded_reasons`
    # exactly as before, even when never_run is also True.
    never_run = last_pipeline_run is None
    degraded_reasons: list[str] = []
    for ch, st in channels.items():
        if st in ("expired", "unreachable"):
            degraded_reasons.append(f"channel:{ch}:{st}")
    if not scheduler_running:
        degraded_reasons.append("scheduler:not_running")

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
        "never_run": never_run,
        "never_run_reason": _NEVER_RUN_REASON if never_run else None,
    }
