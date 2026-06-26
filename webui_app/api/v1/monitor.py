"""Monitoring aggregate endpoint for ``/api/v1`` — Plan 2026-06-18-002 U6.

Single fail-open "today's anomalies first" feed for the Vue monitor dashboard.

REUSES the existing ``command_center`` aggregation rather than recomputing: the
equity-gap / severity / set-difference logic stays server-side (plan R3 +
server-side-gap single-source learning), and the SPA only displays. This is the
versioned ``/api/v1`` binding of the legacy ``/api/monitor-hub`` feed — same
``_collect_subsystem_status`` + ``_build_anomaly_cards``, one source of truth.

Fail-open by design: each subsystem already degrades to an 'unavailable' card,
and a catastrophic aggregator failure returns an empty ``degraded`` payload (200)
so the dashboard shows an empty/degraded state instead of a hard error — one bad
source must never drag down the whole monitor view. Non-sensitive (status counts
+ platform names, no credentials), so it carries no GET-time origin guard.
"""

from __future__ import annotations

from typing import Any

from flask import jsonify

from ...routes.command_center import _build_anomaly_cards, _collect_subsystem_status
from . import bp


@bp.get("/monitor/summary")
def monitor_summary() -> Any:
    """Anomaly-first monitor cards across credentials/keepalive/equity/history."""
    try:
        cards = _build_anomaly_cards(_collect_subsystem_status())
        degraded = False
    except Exception:  # noqa: BLE001 — belt-and-suspenders; aggregator is fail-open
        cards, degraded = [], True
    anomaly_count = sum(1 for c in cards if c["severity"] in ("danger", "warning"))
    return jsonify({"cards": cards, "anomaly_count": anomaly_count, "degraded": degraded})
