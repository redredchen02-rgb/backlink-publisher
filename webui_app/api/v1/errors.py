"""RFC 9457 Problem Details for the ``/api/v1`` surface — Plan 2026-06-18-002 U1.

One error envelope (``application/problem+json``) for the whole versioned JSON
API. It builds on the existing ``PipeResult`` typed-error contract
(``error_class`` / ``exit_code``) rather than inventing a second error
vocabulary — see
``docs/solutions/best-practices/typed-error-envelope-over-stderr-truncation-2026-05-27.md``.

SPA clients branch on the stable ``type`` URI, never on ``title``/``detail``.
"""

from __future__ import annotations

import re
from typing import Any

from flask import Flask, jsonify, request, Response

PROBLEM_CONTENT_TYPE = "application/problem+json"
# Stable, documented type-URI namespace. Opaque to humans, stable for clients.
PROBLEM_TYPE_BASE = "https://backlink-publisher/problems/"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", text.strip().lower()).strip("-") or "error"


class ApiProblem(Exception):
    """Raise inside an ``/api/v1`` handler to emit an RFC 9457 problem+json.

    ``error_class`` is the same vocabulary the CLI typed-error envelope uses, so
    a pipeline failure surfaces under the same ``type`` the rest of the system
    already knows.
    """

    def __init__(
        self,
        status: int,
        title: str,
        *,
        detail: str | None = None,
        type_: str | None = None,
        errors: list[dict[str, Any]] | None = None,
        error_class: str | None = None,
    ) -> None:
        super().__init__(title)
        self.status = status
        self.title = title
        self.detail = detail
        self.error_class = error_class
        self.type = type_ or (PROBLEM_TYPE_BASE + (error_class or _slug(title)))
        self.errors = errors


def problem_dict(
    status: int,
    title: str,
    *,
    detail: str | None = None,
    type_: str | None = None,
    errors: list[dict[str, Any]] | None = None,
    error_class: str | None = None,
    instance: str | None = None,
) -> dict[str, Any]:
    """Build an RFC 9457 problem object. ``status`` always matches the HTTP code."""
    body: dict[str, Any] = {
        "type": type_ or (PROBLEM_TYPE_BASE + (error_class or _slug(title))),
        "title": title,
        "status": status,
    }
    if detail:
        body["detail"] = detail
    if instance:
        body["instance"] = instance
    if error_class:
        body["error_class"] = error_class
    if errors:
        body["errors"] = errors
    return body


def problem_response(problem: ApiProblem) -> Response:
    resp = jsonify(
        problem_dict(
            problem.status,
            problem.title,
            detail=problem.detail,
            type_=problem.type,
            errors=problem.errors,
            error_class=problem.error_class,
            instance=request.path if request else None,
        )
    )
    resp.status_code = problem.status
    resp.headers["Content-Type"] = PROBLEM_CONTENT_TYPE
    return resp


def from_pipe_result(result: Any, *, status: int = 502) -> ApiProblem:
    """Map a failed ``PipeResult`` (success=False) to an ApiProblem.

    Reuses ``error_class`` / ``error`` so the API error vocabulary stays a single
    source of truth with the CLI envelope.
    """
    return ApiProblem(
        status,
        "Pipeline invocation failed",
        detail=getattr(result, "error", None),
        error_class=getattr(result, "error_class", None) or "pipeline_error",
    )


#: Server-side upper bound on a single page's `limit` (Plan 2026-07-02-001 U5).
#: A page this size is already far beyond anything the DataTable UI paginates
#: through by hand; caps a client from forcing one request to serialise/slice
#: an unbounded number of items.
MAX_PAGE_LIMIT = 500


def parse_pagination() -> tuple[int | None, int]:
    """Parse optional ``?limit=&offset=`` query params for a list endpoint.

    Returns ``(None, 0)`` when ``limit`` is absent -- the caller's signal to
    skip pagination entirely and return the flat, pre-U5 ``{items: [...]}}``
    shape unchanged (opt-in incremental pagination, K6: old clients don't
    break). ``offset`` has no effect in this case -- ``?offset=`` alone,
    without ``limit``, is silently ignored, matching the OpenAPI spec's
    per-field description. When ``limit`` is present, both values are
    validated: negative, non-numeric, or oversized (> MAX_PAGE_LIMIT) values
    raise a 400 problem+json rather than silently clamping, since a caller
    passing a malformed value is a client bug worth surfacing, not data worth
    guessing at.
    """
    limit_raw = request.args.get("limit")
    if limit_raw is None:
        return None, 0
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except ValueError:
        raise ApiProblem(
            400, "Invalid pagination parameters",
            detail="`limit`/`offset` must be integers.",
            error_class="invalid_request",
        ) from None
    if limit < 0 or offset < 0:
        raise ApiProblem(
            400, "Invalid pagination parameters",
            detail="`limit`/`offset` must be non-negative.",
            error_class="invalid_request",
        )
    if limit > MAX_PAGE_LIMIT:
        raise ApiProblem(
            400, "Invalid pagination parameters",
            detail=f"`limit` must be <= {MAX_PAGE_LIMIT}.",
            error_class="invalid_request",
        )
    return limit, offset


def paginate(items: list[dict[str, Any]], limit: int | None, offset: int) -> dict[str, Any]:
    """Build the list-endpoint response envelope for a (possibly paginated) list.

    ``limit is None`` (no ``?limit=`` given) returns the original flat
    ``{"items": [...]}`` shape. Otherwise returns the page envelope
    ``{"items": [...], "total": N, "limit": L, "offset": O}`` -- ``total`` is
    the full unpaginated count, so the client can compute page count/clamp
    without a second request.
    """
    if limit is None:
        return {"items": items}
    return {
        "items": items[offset:offset + limit],
        "total": len(items),
        "limit": limit,
        "offset": offset,
    }


def register_api_error_handlers(app: Flask) -> None:
    """Wire RFC 9457 handlers, scoped to ``/api/v1`` so the rest of the app is untouched.

    ``ApiProblem`` is only ever raised by ``/api/v1`` handlers, so its app-level
    handler is safe. The 404/405 handlers customise ONLY ``/api/v1`` paths and
    fall through to Flask's default for every other path (preserving existing
    HTML 404/405 behaviour the test suite asserts on).
    """

    @app.errorhandler(ApiProblem)
    def _handle_api_problem(exc: ApiProblem) -> Response:  # pragma: no cover - thin
        return problem_response(exc)

    @app.errorhandler(404)
    def _handle_404(exc):  # noqa: ANN001
        if request.path.startswith("/api/v1"):
            return problem_response(
                ApiProblem(
                    404,
                    "Not Found",
                    detail=f"No API resource at {request.path}",
                    error_class="not_found",
                )
            )
        return exc.get_response()

    @app.errorhandler(405)
    def _handle_405(exc):  # noqa: ANN001
        if request.path.startswith("/api/v1"):
            return problem_response(
                ApiProblem(405, "Method Not Allowed", error_class="method_not_allowed")
            )
        return exc.get_response()
