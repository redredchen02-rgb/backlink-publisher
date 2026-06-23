"""Work-themed site config endpoints for ``/api/v1`` — Plan 2026-06-18-002 U7.

Migrates the ``/sites`` config page off the legacy Jinja route (render / 302 +
flash). REUSES the ``SitesAPI`` facade — validation, anchor-pool / work-URL
derivation, and the autopilot scheduler sync stay single-source with the helpers
the legacy route also calls.

Stateless + SPA-friendly: mutations return the refreshed ``{items: [...]}`` so
the Pinia/Query cache just replaces its list. Errors are RFC 9457 problem+json:
  * save validation        → 422 with field-level ``errors[]``
  * autopilot bad interval → 422
  * autopilot sched failure→ 502 (store was rolled back — nothing persisted)

Scope note: the embedded batch-operations table (``batch_sites.py``) is NOT
migrated here — it belongs to the dedicated "batch" page unit.
"""

from __future__ import annotations

from flask import jsonify, request

from ..sites_api import SitesAPI
from . import bp
from .errors import ApiProblem

_api = SitesAPI()


@bp.get("/sites")
def sites_list():
    """All configured sites with live autopilot status."""
    return jsonify({"items": _api.list_sites()})


@bp.get("/sites/widgets")
def sites_widgets():
    """Read-only side-panel data: plan-gap weekly summary + citation-share alert."""
    return jsonify(_api.widgets())


@bp.get("/sites/form")
def sites_form():
    """Prefill payload for editing an existing site (``?domain=``), or null."""
    return jsonify({"form": _api.get_form(request.args.get("domain", ""))})


@bp.post("/sites/save")
def sites_save():
    """Validate + derive + persist a three-URL site → refreshed list.

    Validation failure is a 422 problem+json carrying per-field ``errors[]``
    (the SPA renders them inline); success returns the refreshed list plus the
    server-derived field names so the SPA can surface the "autofilled" notice.
    """
    data = request.get_json(silent=True) or {}
    result = _api.save_three_url(data)
    if not result.get("ok"):
        raise ApiProblem(
            422,
            "Site configuration is invalid",
            detail="请修正下方表单错误",
            error_class="invalid_request",
            errors=[{"field": f, "message": m} for f, m in result.get("errors", {}).items()],
        )
    return jsonify({
        "ok": True,
        "saved_domain": result["saved_domain"],
        "autofilled": result.get("autofilled", []),
        "items": _api.list_sites(),
    })


@bp.post("/sites/autopilot")
def sites_autopilot():
    """Enable/disable autopilot for a site → refreshed list.

    Mirrors the legacy endpoint's guards (interval 3600…2592000; missing
    site_url) but maps them onto problem+json: invalid → 422, scheduler-sync
    failure (store rolled back) → 502.
    """
    data = request.get_json(silent=True) or {}
    result = _api.set_autopilot(
        data.get("site_url", ""),
        bool(data.get("enabled", False)),
        data.get("interval_seconds", 86400),
    )
    if not result.get("ok"):
        code = result.get("error_code")
        if code == "SCHEDULER_SYNC_FAILED":
            raise ApiProblem(
                502, "Autopilot scheduler sync failed",
                detail=result.get("detail"), error_class="scheduler_sync_failed",
            )
        # MISSING_SITE_URL / INVALID_INTERVAL — caller-side input problems.
        raise ApiProblem(
            422, "Invalid autopilot request",
            detail=result.get("detail"), error_class="invalid_request",
        )
    return jsonify({**result, "items": _api.list_sites()})


@bp.get("/sites/scrape-preview")
def sites_scrape_preview():
    """Fetch title/description/h1 for a work URL (for the form's preview helper).

    Mirrors the legacy semantics: a fetch/parse failure is a 200 with
    ``{"status": "error", reason}`` (not a transport error), so the SPA shows an
    inline hint; only a missing ``url`` query param is a 422.
    """
    url = (request.args.get("url") or "").strip()
    if not url:
        raise ApiProblem(
            422, "Missing url", detail="`url` query param is required.",
            error_class="invalid_request",
        )
    return jsonify(_api.scrape_preview(url))
