"""Scheduled-drafts read endpoint for ``/api/v1`` — Plan 2026-06-18-002 U7.

Migrates the ``/schedule`` page (a read-only table of drafts with a future
``scheduled_at``) off the legacy Jinja route + ``/api/scheduled`` ESM fetch.
REUSES the existing ``scheduled_api.list_scheduled`` query — no new facade; the
schedule view and the drafts queue stay a single source over ``drafts_store``.

Read-only + fail-soft: a query failure degrades to an empty list (the SPA shows
the empty state), mirroring the legacy route's ``ok``-flag fallback rather than
surfacing a transport error for a pure listing.
"""

from __future__ import annotations

from flask import jsonify

from ..scheduled_api import list_scheduled
from . import bp


@bp.get("/schedule")
def schedule_list():
    """Drafts scheduled for future publish (newest-config order)."""
    result = list_scheduled()
    return jsonify({"items": result.get("items", [])})
