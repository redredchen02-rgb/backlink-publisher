"""Keep-alive status screen (R3 / plan 2026-06-04-001 Unit 4).

The LITE operator's landing surface: a read-only per-target scorecard of which
backlinks are still live vs stripped, bleeding deep pages first, sourced from the
``link.rechecked`` time series (the liveness authority — the ledger column is
stale). The recheck / republish *action* states (S1, S3–S7) land in Units 5–7;
this unit owns the read states (S0 / S2-static / S-stale / empty).
"""
from __future__ import annotations

from flask import Blueprint

from ..helpers.contexts import _render
from ..services.keep_alive import build_keepalive_view

bp = Blueprint("keep_alive", __name__)


@bp.route("/ce:keep-alive", methods=["GET"])
def keep_alive():
    view = build_keepalive_view()
    return _render("keep_alive.html", view=view, active_page="keep_alive")
