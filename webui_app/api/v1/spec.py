"""OpenAPI 3.1 spec builder for ``/api/v1`` — Plan 2026-06-18-002 U1.

The spec is the single source of truth (the "contract linchpin"): it feeds the
CI lint (Spectral), the breaking-change gate (oasdiff), backend conformance
(Schemathesis), and the eventual frontend mocks (Prism/MSW). It is generated
from the marshmallow schemas in ``schemas.py`` plus explicit path declarations
here, so the committed ``openapi/backlink-api.yaml`` can be regenerated and
diffed in CI to catch drift.

Paths are declared explicitly (not introspected from a live app) so spec
generation needs no running server, credentials, or app context.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version
from typing import Any

from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin

from .schemas import (
    AppConfigSchema,
    CsrfTokenSchema,
    HealthSchema,
    HistoryIdRequestSchema,
    HistoryIdsRequestSchema,
    HistoryListSchema,
    HistoryMutationResultSchema,
    MonitorSummarySchema,
    PlanRequestSchema,
    PlanResponseSchema,
    PlatformListSchema,
    PreviewResponseSchema,
    ProblemDetailsSchema,
    ProStatusEnvelopeSchema,
    PublishRequestSchema,
    PublishResponseSchema,
    RegenBodyRequestSchema,
    RegenBodyResponseSchema,
    ValidateRequestSchema,
    ValidateResponseSchema,
)

API_VERSION = "v1"


def app_version() -> str:
    try:
        return _pkg_version("backlink-publisher")
    except PackageNotFoundError:  # pragma: no cover - editable/source checkout
        return "0.0.0"


def _problem_response(description: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            "application/problem+json": {"schema": ProblemDetailsSchema}
        },
    }


def build_spec() -> APISpec:
    spec = APISpec(
        title="Backlink Publisher WebUI API",
        version=app_version(),
        openapi_version="3.1.0",
        plugins=[MarshmallowPlugin()],
        info={
            "description": (
                "Versioned JSON API for the Backlink Publisher WebUI "
                "(Plan 2026-06-18-002, front/back separation). Single-origin: "
                "served same-origin by Flask. Errors use RFC 9457 problem+json."
            ),
        },
    )
    spec.components.schema("Health", schema=HealthSchema)
    spec.components.schema("ProblemDetails", schema=ProblemDetailsSchema)
    spec.components.schema("PlatformList", schema=PlatformListSchema)
    spec.components.schema("ProStatusEnvelope", schema=ProStatusEnvelopeSchema)
    spec.components.schema("AppConfig", schema=AppConfigSchema)
    spec.components.schema("CsrfToken", schema=CsrfTokenSchema)
    spec.components.schema("PlanRequest", schema=PlanRequestSchema)
    spec.components.schema("PlanResponse", schema=PlanResponseSchema)
    spec.components.schema("PreviewResponse", schema=PreviewResponseSchema)
    spec.components.schema("ValidateRequest", schema=ValidateRequestSchema)
    spec.components.schema("ValidateResponse", schema=ValidateResponseSchema)
    spec.components.schema("PublishRequest", schema=PublishRequestSchema)
    spec.components.schema("PublishResponse", schema=PublishResponseSchema)
    spec.components.schema("RegenBodyRequest", schema=RegenBodyRequestSchema)
    spec.components.schema("RegenBodyResponse", schema=RegenBodyResponseSchema)
    spec.components.schema("MonitorSummary", schema=MonitorSummarySchema)
    spec.components.schema("HistoryList", schema=HistoryListSchema)
    spec.components.schema("HistoryMutationResult", schema=HistoryMutationResultSchema)
    spec.components.schema("HistoryIdRequest", schema=HistoryIdRequestSchema)
    spec.components.schema("HistoryIdsRequest", schema=HistoryIdsRequestSchema)

    def _ok(description: str, schema: Any) -> dict[str, Any]:
        return {"description": description, "content": {"application/json": {"schema": schema}}}

    def _body(schema: Any) -> dict[str, Any]:
        return {"required": True, "content": {"application/json": {"schema": schema}}}

    spec.path(
        path="/api/v1/health",
        operations={
            "get": {
                "operationId": "getHealth",
                "summary": "Liveness probe.",
                "description": "Returns service liveness and version. No auth, no side effects.",
                "tags": ["meta"],
                "responses": {
                    "200": _ok("Service is up.", HealthSchema),
                    "404": _problem_response("Unknown API resource."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/app-config",
        operations={
            "get": {
                "operationId": "getAppConfig",
                "summary": "SPA bootstrap config (edition, Pro status, version).",
                "description": "Origin-guarded GET. Replaces the Jinja context-processor injection.",
                "tags": ["bootstrap"],
                "responses": {
                    "200": _ok("Bootstrap config.", AppConfigSchema),
                    "403": _problem_response("Cross-origin / DNS-rebinding GET rejected."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/csrf-token",
        operations={
            "get": {
                "operationId": "getCsrfToken",
                "summary": "Per-session CSRF token for the SPA fetch layer.",
                "description": "Origin-guarded GET. Re-read per mutating call; never cache.",
                "tags": ["bootstrap"],
                "responses": {
                    "200": _ok("CSRF token.", CsrfTokenSchema),
                    "403": _problem_response("Cross-origin / DNS-rebinding GET rejected."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/platforms",
        operations={
            "get": {
                "operationId": "getPlatforms",
                "summary": "Full registered-platform list.",
                "tags": ["bootstrap"],
                "responses": {"200": _ok("Platform list.", PlatformListSchema)},
            }
        },
    )
    spec.path(
        path="/api/v1/bound-platforms",
        operations={
            "get": {
                "operationId": "getBoundPlatforms",
                "summary": "Bound + manifest-visible platforms (publish-form filter).",
                "tags": ["bootstrap"],
                "responses": {"200": _ok("Bound platform list.", PlatformListSchema)},
            }
        },
    )
    spec.path(
        path="/api/v1/pro-status",
        operations={
            "get": {
                "operationId": "getProStatus",
                "summary": "Pro-Mode visibility summary (redaction-safe).",
                "tags": ["bootstrap"],
                "responses": {"200": _ok("Pro status.", ProStatusEnvelopeSchema)},
            }
        },
    )
    spec.path(
        path="/api/v1/pipeline/plan",
        operations={
            "post": {
                "operationId": "planBacklinks",
                "summary": "Generate article plans for the given URLs.",
                "description": "Stateless: takes inputs in the body, returns plan rows.",
                "tags": ["pipeline"],
                "requestBody": _body(PlanRequestSchema),
                "responses": {
                    "200": _ok("Generated plan rows.", PlanResponseSchema),
                    "422": _problem_response("Invalid request (e.g. missing urls)."),
                    "502": _problem_response("Generation failed or produced no output."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/pipeline/preview",
        operations={
            "post": {
                "operationId": "previewBacklink",
                "summary": "Single-article preview (plan one seed, return first row).",
                "tags": ["pipeline"],
                "requestBody": _body(PlanRequestSchema),
                "responses": {
                    "200": _ok("First planned row (or null).", PreviewResponseSchema),
                    "422": _problem_response("Invalid request."),
                    "502": _problem_response("Generation failed."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/pipeline/validate",
        operations={
            "post": {
                "operationId": "validateBacklinks",
                "summary": "Validate plan rows (URL checks skipped server-side).",
                "tags": ["pipeline"],
                "requestBody": _body(ValidateRequestSchema),
                "responses": {
                    "200": _ok("Validated rows.", ValidateResponseSchema),
                    "422": _problem_response("Invalid request or validation error."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/pipeline/publish",
        operations={
            "post": {
                "operationId": "publishBacklinks",
                "summary": "Publish validated rows to a platform (synchronous).",
                "description": (
                    "Partial success returns 200 with per-row outcomes in `results`; "
                    "total failure is a problem+json. No pollable task-id (synchronous)."
                ),
                "tags": ["pipeline"],
                "requestBody": _body(PublishRequestSchema),
                "responses": {
                    "200": _ok("Aggregate publish result.", PublishResponseSchema),
                    "400": _problem_response("Credential precondition failed (e.g. velog)."),
                    "401": _problem_response("Auth/credential error."),
                    "422": _problem_response("Invalid request."),
                    "502": _problem_response("Publish failed / no result rows."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/history",
        operations={
            "get": {
                "operationId": "getHistory",
                "summary": "Full publish-history list.",
                "tags": ["history"],
                "responses": {"200": _ok("History list.", HistoryListSchema)},
            }
        },
    )
    spec.path(
        path="/api/v1/history/delete",
        operations={
            "post": {
                "operationId": "deleteHistoryItem",
                "summary": "Delete one history entry → refreshed list.",
                "tags": ["history"],
                "requestBody": _body(HistoryIdRequestSchema),
                "responses": {
                    "200": _ok("Refreshed list.", HistoryMutationResultSchema),
                    "422": _problem_response("Missing id."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/history/bulk-delete",
        operations={
            "post": {
                "operationId": "bulkDeleteHistory",
                "summary": "Delete multiple history entries → refreshed list.",
                "tags": ["history"],
                "requestBody": _body(HistoryIdsRequestSchema),
                "responses": {
                    "200": _ok("Refreshed list.", HistoryMutationResultSchema),
                    "422": _problem_response("Missing ids."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/history/purge-failed",
        operations={
            "post": {
                "operationId": "purgeFailedHistory",
                "summary": "Delete every 'failed' entry → refreshed list.",
                "tags": ["history"],
                "responses": {"200": _ok("Refreshed list.", HistoryMutationResultSchema)},
            }
        },
    )
    spec.path(
        path="/api/v1/history/recheck",
        operations={
            "post": {
                "operationId": "recheckHistoryItem",
                "summary": "Re-verify one history entry's link liveness → refreshed list.",
                "tags": ["history"],
                "requestBody": _body(HistoryIdRequestSchema),
                "responses": {
                    "200": _ok("Refreshed list.", HistoryMutationResultSchema),
                    "404": _problem_response("History item not found."),
                    "422": _problem_response("Missing id."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/monitor/summary",
        operations={
            "get": {
                "operationId": "getMonitorSummary",
                "summary": "Anomaly-first monitor aggregate (today's anomalies first).",
                "description": (
                    "Fail-open aggregate across credentials/keepalive/equity/history. "
                    "Severity + equity-gap computed server-side (single source); the SPA "
                    "only displays. Versioned binding of the legacy /api/monitor-hub feed."
                ),
                "tags": ["monitor"],
                "responses": {
                    "200": _ok("Anomaly-first card feed.", MonitorSummarySchema),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/pipeline/regen-body",
        operations={
            "post": {
                "operationId": "regenArticleBody",
                "summary": "Re-generate one article body via the configured LLM.",
                "tags": ["pipeline"],
                "requestBody": _body(RegenBodyRequestSchema),
                "responses": {
                    "200": _ok("Regenerated body (markdown + html).", RegenBodyResponseSchema),
                    "400": _problem_response("LLM not configured."),
                    "422": _problem_response("Invalid request."),
                    "502": _problem_response("LLM call failed."),
                },
            }
        },
    )
    return spec


def spec_dict() -> dict[str, Any]:
    return build_spec().to_dict()


def spec_yaml() -> str:
    return build_spec().to_yaml()
