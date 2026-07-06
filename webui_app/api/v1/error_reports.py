"""``/api/v1/error-reports`` -- JSON API for frontend error capture + the
operator diagnostics dashboard (Plan 2026-07-01-002 Unit 3).

Both frontends (legacy Jinja/JS pages and the Vue SPA) POST auto-captured
and manually-typed error reports here; the SPA dashboard (Unit 8) reads them
back via the GET endpoints. Every persisted byte has already passed through
Unit 1's :func:`sanitize_error_report` -- this module never writes a raw,
unsanitized client payload to :data:`error_report_store` (Unit 2).

Fingerprint merge (R1/R4/R5): a POST tied to an auto-captured error (carries
a truthy ``reportId`` -- a client-side correlation id minted the moment the
underlying JS error/rejection was first caught, NOT a server-assigned row
id, which does not exist yet at POST time) is deduplicated server-side by
``fingerprint`` against :meth:`error_report_store.find_by_fingerprint`: a
match whose ``status`` is not yet ``"resolved"`` gets its occurrence count
bumped via :meth:`error_report_store.increment_occurrence` instead of a new
row being added. A match that IS already ``"resolved"`` means the
underlying bug recurred *after* being marked fixed, so a fresh row is added
instead of resurrecting the closed one (``find_by_fingerprint`` is
deliberately status-agnostic per its own docstring in
``webui_store/error_reports.py`` -- the open/resolved merge *policy* lives
here, in the endpoint, not in persistence).

A manual report (no ``reportId`` at all -- the nav-bar "report a problem"
panel, Unit 5/7) always calls :meth:`error_report_store.add`, even if its
payload happens to carry a ``fingerprint`` that matches an existing row: a
user who typed out a report and hit submit must never have it silently
folded into another row's occurrence count.

Failure logging (this endpoint's own persistence-failure path) never logs
the raw pre-sanitized payload or a raw exception message -- only a
sanitized-field summary (``error_class``, ``source``, ``severity``, all
already scrubbed by Unit 1 by the time they reach the log call). This
mirrors a gap the plan's review flagged in ``drafts_api.py``'s
``plan_logger.error(..., error=str(exc))`` convention, which logs by
key-name redaction only (``error`` is not in ``_SENSITIVE_KEYS``) and never
calls ``scrub_text`` -- safe to reuse for already-sanitized fields, unsafe
for a raw exception message that might echo unsanitized input back.

CSRF: no endpoint-specific handling here -- the app-level
``_global_csrf_guard`` (``webui_app/__init__.py``) already covers every
POST/PUT/PATCH/DELETE. There is no OAuth-callback-style reason to exempt
this surface.
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
import tomllib
from typing import Any, Final

from flask import jsonify, request

from backlink_publisher._util.logger import plan_logger
from backlink_publisher.config.loader import _config_dir
from webui_store.error_reports import error_report_store, STATUS_VALUES

from ...services.error_report_sanitizer import sanitize_error_report
from . import bp
from .errors import ApiProblem

#: Request-body size ceiling, mirroring
#: ``channel_bind_api.py``'s guard against ``credential_service._PASTE_BLOB_MAX_BYTES``
#: (100 KB) -- checked against ``request.content_length`` BEFORE any JSON
#: parsing. The browser-side fetch/keepalive 64KB cap is not a substitute:
#: it constrains only a browser tab, not any other loopback-capable process,
#: and the site sets no app-wide ``MAX_CONTENT_LENGTH``.
_MAX_REQUEST_BYTES: Final[int] = 100_000

#: Fallback retention window (days) when ``[error_reports].retention_days``
#: is absent or not a positive int -- a reasonable starting point per the
#: plan's "Deferred to Implementation" note; tune once real volume is known.
_DEFAULT_RETENTION_DAYS: Final[int] = 30

#: The one status value that exempts a fingerprint match from being
#: incremented -- see the module docstring's "resolved-recurrence" note.
_RESOLVED_STATUS: Final[str] = "resolved"


# ── config: [error_reports] section (best-effort, no caching) ──────────────


def _load_error_reports_settings() -> dict[str, Any]:
    """Read the ``[error_reports]`` TOML table, if any.

    Read directly at the TOML level (not through
    ``backlink_publisher.config.Config``, which has no managed field for
    this table -- Unit 3 does not add one) so a missing/corrupt
    ``config.toml`` degrades to "no settings configured" rather than
    raising. Not cached (unlike ``load_config()``'s 15s TTL cache): this
    table is tiny and read only on the POST/PATCH/purge paths, never in a
    per-request-hot loop.
    """
    config_path = _config_dir() / "config.toml"
    if not config_path.exists():
        return {}
    try:
        with config_path.open("rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError):
        return {}
    section = data.get("error_reports")
    return section if isinstance(section, dict) else {}


def _today_start_iso() -> str:
    now = datetime.now(UTC)
    return datetime(now.year, now.month, now.day, tzinfo=UTC).isoformat()


def _enforce_daily_cap() -> None:
    """Raise an ``ApiProblem`` (429) if today's new-row quota is exhausted.

    Only counts rows genuinely inserted today (``created_at`` >= midnight
    UTC) -- ``increment_occurrence()`` never touches ``created_at``, so a
    repeating bug's occurrence bump never consumes this quota (see the
    module docstring). Best-effort check-then-act (not atomic with the
    ``add()`` call that follows): mirrors this store family's already-
    accepted single-process concurrency posture (see
    ``docs/solutions/architecture-patterns/2026-06-05-lite-accepted-deferrals.md``)
    -- a race under heavy concurrent load could let one extra row past the
    cap, an acceptable coarse-quota trade-off rather than a hard atomicity
    guarantee.
    """
    settings = _load_error_reports_settings()
    daily_cap = settings.get("daily_cap")
    if not isinstance(daily_cap, int) or daily_cap < 0:
        return  # absent / non-int / negative -> unlimited
    count_today = len(error_report_store.list(filters={"since": _today_start_iso()}))
    if count_today >= daily_cap:
        raise ApiProblem(
            429,
            "Daily error-report cap exceeded",
            detail=(
                f"The configured daily cap of {daily_cap} new error reports "
                "has already been reached today."
            ),
            error_class="daily_cap_exceeded",
        )


# ── request-size guard ──────────────────────────────────────────────────────


def _guard_request_size() -> None:
    """Reject an oversized body before any JSON parsing (413 problem+json).

    Trusts the ``Content-Length`` header for this fast pre-parse rejection
    -- a non-browser caller that can reach loopback is not bound by the
    browser fetch/keepalive 64KB limit, so this endpoint enforces its own
    ceiling rather than relying on that browser-side behaviour.
    """
    length = request.content_length
    if length is not None and length > _MAX_REQUEST_BYTES:
        raise ApiProblem(
            413,
            "Error report too large",
            detail=(
                f"Request body exceeds the {_MAX_REQUEST_BYTES // 1000}KB "
                "limit for a single error report."
            ),
            error_class="payload_too_large",
        )


# ── POST /error-reports ─────────────────────────────────────────────────────


@bp.post("/error-reports")
def create_error_report() -> Any:
    """Persist a sanitized error report; merge into an existing fingerprint
    when applicable. See the module docstring for the full merge contract."""
    _guard_request_size()

    raw = request.get_json(silent=True)
    sanitized = sanitize_error_report(raw)

    # A truthy `reportId` ties this submission to a specific auto-captured
    # error instance (client-minted correlation id -- see module docstring);
    # its absence means a manual, free-text report that must never be
    # folded into another row's occurrence count, regardless of whether it
    # happens to also carry a `fingerprint`.
    is_manual = not (isinstance(raw, dict) and raw.get("reportId"))
    fingerprint = None if is_manual else sanitized.get("fingerprint")

    try:
        if fingerprint:
            existing = error_report_store.find_by_fingerprint(fingerprint)
            if existing is not None and existing.get("status") != _RESOLVED_STATUS:
                existing_id = existing["id"]
                if error_report_store.increment_occurrence(existing_id):
                    updated = error_report_store.get(existing_id) or existing
                    return jsonify({
                        "id": existing_id,
                        "occurrences": updated.get("occurrences"),
                    }), 200
                # else: the row vanished between find and increment (rare
                # race) -- fall through and add a fresh row instead.

        _enforce_daily_cap()
        # A brand-new report always starts "open" regardless of any
        # client-supplied `status` -- that field describes operator triage
        # state, not something a submitting client should get to dictate.
        to_persist = {k: v for k, v in sanitized.items() if k != "status"}
        new_id = error_report_store.add(to_persist)
        return jsonify({"id": new_id}), 201
    except ApiProblem:
        raise
    except Exception as exc:
        plan_logger.error(
            "error_report_persist_failed",
            error_class=type(exc).__name__,
            source=sanitized.get("source"),
            severity=sanitized.get("severity"),
        )
        raise ApiProblem(
            502,
            "Error report persistence failed",
            detail="Failed to persist the error report; see server logs.",
            error_class="persistence_failure",
        )


# ── GET /error-reports (list) ───────────────────────────────────────────────


@bp.get("/error-reports")
def list_error_reports() -> Any:
    """Filterable, paginated list for the operator dashboard.

    Fail-soft like the rest of this API's read-only GETs: an unrecognised
    filter value is passed straight through to the store (which does exact
    matching) rather than 400ing -- it simply yields zero rows.
    """
    filters: dict[str, Any] = {}
    for key in ("status", "severity", "source", "fingerprint", "since", "until"):
        value = request.args.get(key)
        if value:
            filters[key] = value

    items = error_report_store.list(filters=filters or None)
    total = len(items)

    limit = request.args.get("limit", type=int)
    offset = request.args.get("offset", type=int) or 0
    if offset:
        items = items[offset:]
    if limit is not None:
        items = items[:limit]

    return jsonify({"items": items, "total": total})


# ── GET /error-reports/<id> ──────────────────────────────────────────────────


@bp.get("/error-reports/<report_id>")
def get_error_report(report_id: str) -> Any:
    """Single-report detail for dashboard drill-down."""
    report = error_report_store.get(report_id)
    if report is None:
        raise ApiProblem(
            404,
            "Error report not found",
            detail=f"No error report with id {report_id!r}.",
            error_class="not_found",
        )
    return jsonify(report)


# ── PATCH /error-reports/<id> ─────────────────────────────────────────────────


@bp.patch("/error-reports/<report_id>")
def update_error_report(report_id: str) -> Any:
    """Attach a user description and/or update status on an existing report."""
    _guard_request_size()

    existing = error_report_store.get(report_id)
    if existing is None:
        raise ApiProblem(
            404,
            "Error report not found",
            detail=f"No error report with id {report_id!r}.",
            error_class="not_found",
        )

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}

    status = body.get("status")
    if status is not None and status not in STATUS_VALUES:
        raise ApiProblem(
            400,
            "Invalid status",
            detail=f"status must be one of {sorted(STATUS_VALUES)}, got {status!r}.",
            error_class="invalid_request",
        )

    description = body.get("description") if "description" in body else None
    if description is not None and not isinstance(description, str):
        description = str(description)

    try:
        if description is not None:
            # Reuse Unit 1's sanitizer for the one free-text field this
            # endpoint accepts -- the plan's own security review names this
            # exact field as the most likely place an operator pastes a
            # credential while describing a problem.
            sanitized_desc = sanitize_error_report(
                {"user_description": description}
            ).get("user_description", "")
            error_report_store.attach_description(report_id, sanitized_desc)
        if status is not None:
            error_report_store.update_status(report_id, status)
    except Exception as exc:
        plan_logger.error(
            "error_report_update_failed",
            error_class=type(exc).__name__,
            report_id=report_id,
        )
        raise ApiProblem(
            502,
            "Error report update failed",
            detail="Failed to update the error report; see server logs.",
            error_class="persistence_failure",
        )

    updated = error_report_store.get(report_id) or existing
    return jsonify(updated), 200


# ── DELETE /error-reports/<id> ────────────────────────────────────────────────


@bp.delete("/error-reports/<report_id>")
def delete_error_report(report_id: str) -> Any:
    """Manual remediation path for a report suspected of residual leakage."""
    deleted = error_report_store.delete(report_id)
    if not deleted:
        raise ApiProblem(
            404,
            "Error report not found",
            detail=f"No error report with id {report_id!r}.",
            error_class="not_found",
        )
    return jsonify({"ok": True, "id": report_id}), 200


# ── Periodic purge (wired into webui_app/scheduler.py) ──────────────────────


def purge_expired_error_reports() -> int:
    """Delete every report whose ``created_at`` is past the retention window.

    Returns the number of rows actually removed. Best-effort per row: a
    delete failure on one row is logged (sanitized -- id + error class
    only) and skipped rather than aborting the whole sweep, mirroring
    ``scheduler.py``'s ``_drain_batch_ops`` per-item isolation.
    """
    settings = _load_error_reports_settings()
    retention_days = settings.get("retention_days")
    if not isinstance(retention_days, int) or retention_days <= 0:
        retention_days = _DEFAULT_RETENTION_DAYS

    cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
    expired = error_report_store.list(filters={"until": cutoff})

    removed = 0
    for report in expired:
        report_id = report.get("id")
        if not report_id:
            continue
        try:
            if error_report_store.delete(report_id):
                removed += 1
        except Exception as exc:
            plan_logger.warn(
                "error_report_purge_row_failed",
                report_id=report_id,
                error_class=type(exc).__name__,
            )
    return removed
