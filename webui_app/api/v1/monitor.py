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

``degraded`` (R18 fix): true when the aggregator itself crashes OR when any
individual subsystem's own try/except caught an error. Previously only the
former set it, so a single silently-broken source could leave the
"everything's fine" banner showing even though its own card had quietly
degraded to 'unavailable'.

Plan 2026-07-06-004 Unit 2 extended the aggregator to 6 signal sources total:
the original 4 (credentials/keepalive/equity/history) plus an error-reports
backlog and a schedule/queue backlog. The two new cards are "hybrid" — they
carry an optional ``items`` list (the first N individual items) alongside the
usual aggregate fields — but that shape lives entirely inside
``_build_anomaly_cards()``'s card dicts, so this endpoint needed no code
change beyond this docstring: whatever cards the aggregator returns are
serialized as-is.
"""

from __future__ import annotations

from typing import Any

from flask import jsonify

from ...routes.command_center import (
    _any_subsystem_error,
    _build_anomaly_cards,
    _collect_subsystem_status,
)
from . import bp


@bp.get("/monitor/summary")
def monitor_summary() -> Any:
    """Anomaly-first monitor cards across all 6 signal sources (see module docstring)."""
    try:
        status = _collect_subsystem_status()
        cards = _build_anomaly_cards(status)
        degraded = _any_subsystem_error(status)
    except Exception:  # noqa: BLE001 — belt-and-suspenders; aggregator is fail-open
        # debt: monitor-summary-aggregator-fail-open
        cards, degraded = [], True
    anomaly_count = sum(1 for c in cards if c["severity"] in ("danger", "warning"))
    return jsonify({"cards": cards, "anomaly_count": anomaly_count, "degraded": degraded})
