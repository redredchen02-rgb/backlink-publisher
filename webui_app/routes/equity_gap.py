"""Fill Gaps — POST endpoint per weak target (Plan 2026-06-05-001 U4).

Calls the plan-gap engine concepts in-process to return missing platforms,
deficiency, and a ready-to-use CLI command. Read-only (advisory).
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from backlink_publisher._util.url import canonicalize_url
from backlink_publisher.ledger import build_ledger
from backlink_publisher.publishing.registry import (
    dofollow_status,
    registered_platforms,
)

bp = Blueprint("equity_gap", __name__)

_STALE_DAYS_DEFAULT: int = 30


def _active_dofollow_platforms() -> list[str]:
    return sorted(
        p for p in registered_platforms() if dofollow_status(p) is True
    )


@bp.route("/ce:equity-ledger/fill-gaps", methods=["POST"])
def fill_gaps():
    data = request.get_json(silent=True) or {}
    target = (data.get("target_url") or "").strip()
    if not target:
        return jsonify({"error": "target_url required"}), 400

    try:
        stale_days = int(data.get("stale_days", _STALE_DAYS_DEFAULT))
    except (TypeError, ValueError):
        stale_days = _STALE_DAYS_DEFAULT
    if stale_days <= 0:
        stale_days = _STALE_DAYS_DEFAULT

    canon = canonicalize_url(target)
    rows = build_ledger(stale_days=stale_days)
    row = next((r for r in rows if r.target_url == canon), None)
    if row is None:
        return jsonify({"error": "target not found"}), 404

    live_set = frozenset(row.live_dofollow_platforms or [])
    missing = sorted(p for p in _active_dofollow_platforms() if p not in live_set)
    deficiency = max(0, 3 - (row.live_dofollow or 0))

    desired = max(1, deficiency + 1)
    cli_cmd = (
        f"equity-ledger | grep '{canon}' | plan-gap --desired {desired} --language zh-CN | plan-backlinks"
    )

    return jsonify({
        "target_url": canon,
        "missing_platforms": missing,
        "deficiency": deficiency,
        "cli_command": cli_cmd,
    })
