"""Event-store helpers for click-track events (Plan 2026-06-02-001).

Each helper builds a :class:`ClickRow` and calls
``store.append(kind, payload)``.

Public surface
--------------
* :func:`append_observed`
* :func:`append_query_failed`
* :func:`append_query_skipped`
* :class:`ClickRow`
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class ClickRow:
    """Denormalised representation of one ``click.*`` event row."""

    target_site: str
    kind: str
    source_domain: str | None = None
    sessions: int | None = None
    users: int | None = None
    pageviews: int | None = None
    window_start: str | None = None
    window_end: str | None = None
    error_reason: str | None = None
    ts: str = ""


def append_observed(
    store: object,
    *,
    target_site: str,
    sessions: int,
    users: int,
    pageviews: int,
    window_start: str,
    window_end: str,
    source_url: str | None = None,
) -> None:
    """Record a ``click.observed`` event for a successful GA4 query."""
    store.append("click.observed", {
        "target_site": target_site,
        "source_domain": source_url,
        "sessions": sessions,
        "users": users,
        "pageviews": pageviews,
        "window_start": window_start,
        "window_end": window_end,
        "ts": datetime.now(timezone.utc).isoformat(),
    })


def append_query_failed(
    store: object,
    target_site: str,
    *,
    error_reason: str,
) -> None:
    """Record a ``click.query_failed`` event."""
    store.append("click.query_failed", {
        "target_site": target_site,
        "error_reason": error_reason,
        "ts": datetime.now(timezone.utc).isoformat(),
    })


def append_query_skipped(
    store: object,
    target_site: str,
    *,
    reason: str,
) -> None:
    """Record a ``click.query_skipped`` event."""
    store.append("click.query_skipped", {
        "target_site": target_site,
        "error_reason": reason,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
