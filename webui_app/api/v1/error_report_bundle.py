"""``POST /api/v1/error-reports/export-bundle`` -- render a coding-agent-ready
diagnostic bundle from a failed pipeline run's captured context (Plan
2026-07-09-001).

This is the WebUI counterpart to the ``bp-report-bug`` CLI. The WebUI already
holds the full stderr + typed-error envelope of a failed run (via
``backui_app.helpers.cli_runner``), so a "report error" button can POST that
context here and get back a self-contained Markdown bundle to hand to a coding
agent.

Sanitization reuses the existing Unit-1 sanitizer
(:func:`webui_app.services.error_report_sanitizer.sanitize_error_report`,
which composes free-text scrubbing, structured key-name redaction, AND exact
known-credential-value matching -- strictly stronger than the core CLI's own
regex scrubber). The bundle is then enriched with environment / config /
storage-health / recent-run context and rendered by the shared core builder
(:mod:`backlink_publisher.cli.report_bug._build`), so the CLI and WebUI paths
produce identically-shaped output from one source of truth.

CSRF: covered by the app-level ``_global_csrf_guard`` (every POST/PUT/PATCH/
DELETE). Request size is bounded before any JSON parse, mirroring
``error_reports.py``.
"""

from __future__ import annotations

from typing import Any

from flask import jsonify, request

from backlink_publisher._util.error_envelope import ErrorEnvelope
from backlink_publisher._util.logger import plan_logger
from backlink_publisher._util.paths import _cache_dir
from backlink_publisher.cli.report_bug._build import (
    build_report,
    render_markdown,
    ReportInput,
    save_report,
)
from webui_app.services.error_report_sanitizer import sanitize_error_report

from . import bp
from .errors import ApiProblem

#: Same 100 KB ceiling as error_reports.py (channel_bind_api.py precedent).
_MAX_REQUEST_BYTES: int = 100_000


def _guard_request_size() -> None:
    """Reject an oversized body before any JSON parsing (413 problem+json)."""
    length = request.content_length
    if length is not None and length > _MAX_REQUEST_BYTES:
        raise ApiProblem(
            413,
            "Error bundle too large",
            detail=(
                f"Request body exceeds the {_MAX_REQUEST_BYTES // 1000}KB "
                "limit for a single error bundle."
            ),
            error_class="payload_too_large",
        )


def _bundle_dir() -> str:
    return str(_cache_dir() / "bug-reports")


@bp.post("/error-reports/export-bundle")
def export_error_bundle() -> Any:
    """Build a redacted diagnostic bundle from a failed run's context.

    Body (all optional except implied by the failure):
      - ``stderr`` (str): captured stderr of the failed command/run.
      - ``error_class`` (str): typed error class (e.g. ``AuthExpiredError``).
      - ``exit_code`` (int): the command's exit code.
      - ``message`` (str): the error message.
      - ``run_id`` (str): associated checkpoint run id (repro hint).
      - ``command`` (str): the original command (repro hint).
      - ``description`` (str): free-text operator description.
    """
    _guard_request_size()

    raw = request.get_json(silent=True)
    if not isinstance(raw, dict):
        raise ApiProblem(
            400,
            "Invalid body",
            detail="Expected a JSON object.",
            error_class="invalid_request",
        )

    stderr = raw.get("stderr") or ""
    description = raw.get("description") or ""

    # Sanitize free text via the existing Unit-1 sanitizer (Layer 1/2/3).
    sanitized = sanitize_error_report({"stderr": stderr, "user_description": description})
    safe_stderr = sanitized.get("stderr", "")
    safe_desc = sanitized.get("user_description", "")

    envelope: ErrorEnvelope | None = None
    if raw.get("error_class") or raw.get("message"):
        try:
            envelope = ErrorEnvelope(
                error_class=str(raw.get("error_class") or "unknown"),
                exit_code=int(raw.get("exit_code") or 0),
                message=str(raw.get("message") or ""),
            )
        except (ValueError, TypeError):
            envelope = None

    inp = ReportInput(
        envelope=envelope,
        stderr_text=safe_stderr,
        command=raw.get("command"),
        run_id=raw.get("run_id"),
        describe=safe_desc or None,
    )

    try:
        report = build_report(inp, redact=True)
        md_path, json_path = save_report(report, _bundle_dir(), redact=True)
        markdown = render_markdown(report)
    except Exception as exc:  # noqa: BLE001 — never leak a raw traceback to the client
        plan_logger.error("error_bundle_build_failed", error_class=type(exc).__name__)
        raise ApiProblem(
            502,
            "Error bundle build failed",
            detail="Failed to assemble the diagnostic bundle; see server logs.",
            error_class="persistence_failure",
        )

    return jsonify(
        {
            "markdown": markdown,
            "report_path": str(md_path),
            "json_path": str(json_path),
        }
    )
