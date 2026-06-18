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
    PlatformListSchema,
    ProblemDetailsSchema,
    ProStatusEnvelopeSchema,
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

    def _ok(description: str, schema: Any) -> dict[str, Any]:
        return {"description": description, "content": {"application/json": {"schema": schema}}}

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
    return spec


def spec_dict() -> dict[str, Any]:
    return build_spec().to_dict()


def spec_yaml() -> str:
    return build_spec().to_yaml()
