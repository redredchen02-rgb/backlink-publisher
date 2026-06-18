"""SPA catch-all — serves the built Vue app under ``/app/*`` (Plan 2026-06-18-002 U3).

Single-origin: the SPA bundle (``frontend/`` built into ``webui_app/spa_dist``)
is served by Flask, so there is no second origin and the existing
loopback + same-origin + CSRF model is preserved.

Flag-gated by ``BACKLINK_PUBLISHER_SPA`` so it is inert by default — the legacy
Jinja UI stays the default through the strangler-fig migration, and ``/app``
404s until an operator opts in (and the bundle has actually been built).

Routing: an existing file under ``spa_dist`` is served verbatim (hashed assets
at ``/app/assets/*``); anything else returns ``index.html`` so client-side routes
resolve on a hard refresh. The build lives OUTSIDE ``webui_app/static`` so it
neither collides with Flask's ``/static`` route nor gets walked by
``_compute_asset_version`` at boot. ``/api`` is a different prefix and is never
shadowed.
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Blueprint, abort, send_from_directory

bp = Blueprint("spa", __name__)

_SPA_DIR = Path(__file__).resolve().parent.parent / "spa_dist"


def _spa_enabled() -> bool:
    return os.environ.get("BACKLINK_PUBLISHER_SPA", "0") == "1"


@bp.get("/app")
@bp.get("/app/")
@bp.get("/app/<path:subpath>")
def spa(subpath: str = ""):
    if not _spa_enabled():
        abort(404)
    if not (_SPA_DIR / "index.html").is_file():
        abort(404)  # bundle not built
    if subpath:
        candidate = (_SPA_DIR / subpath).resolve()
        spa_root = _SPA_DIR.resolve()
        # Serve a real built file (asset) only when it resolves INSIDE spa_dist
        # (defends against path traversal); otherwise fall through to index.html.
        if candidate.is_file() and spa_root in candidate.parents:
            return send_from_directory(spa_root, subpath)
    return send_from_directory(_SPA_DIR.resolve(), "index.html")
