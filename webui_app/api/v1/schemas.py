"""marshmallow schemas for ``/api/v1`` — Plan 2026-06-18-002 U1.

These are the request/response DTOs the OpenAPI 3.1 spec is generated from
(apispec ``MarshmallowPlugin``). marshmallow ships with apiflask; it is the
API-edge schema layer and is deliberately separate from the domain's pydantic
models. Wire format is snake_case; timestamps are RFC 3339 UTC; ids are strings.
"""

from __future__ import annotations

from marshmallow import Schema, fields


class HealthSchema(Schema):
    """Liveness probe response."""

    status = fields.String(
        required=True, metadata={"description": "Always 'ok' when the service is up."}
    )
    api_version = fields.String(
        required=True, metadata={"description": "Major API version, e.g. 'v1'."}
    )
    version = fields.String(
        required=True, metadata={"description": "backlink-publisher package version."}
    )


class PlatformSchema(Schema):
    """One publisher platform (registry-derived)."""

    slug = fields.String(required=True)
    display_name = fields.String(required=True)


class PlatformListSchema(Schema):
    """Object envelope around a platform list (never a bare top-level array)."""

    platforms = fields.List(fields.Nested(PlatformSchema), required=True)


class ProStatusSchema(Schema):
    """Redaction-safe Pro-Mode summary — never includes the api_key."""

    configured = fields.Boolean(required=True)
    endpoint_host = fields.String()
    model = fields.String()
    article_gen = fields.Boolean()
    image_gen = fields.Boolean()
    last_test = fields.Raw(allow_none=True)


class ProStatusEnvelopeSchema(Schema):
    pro_status = fields.Nested(ProStatusSchema, required=True)


class AppConfigSchema(Schema):
    """SPA bootstrap payload — edition, Pro status, version."""

    api_version = fields.String(required=True)
    version = fields.String(required=True)
    lite_edition = fields.Boolean(required=True)
    pro_status = fields.Nested(ProStatusSchema, required=True)
    llm_configured = fields.Boolean(required=True)


class CsrfTokenSchema(Schema):
    """Per-session CSRF token for the SPA fetch layer (re-read per call)."""

    csrf_token = fields.String(required=True)


class ProblemErrorItemSchema(Schema):
    """One field-level validation error inside a ProblemDetails.errors[]."""

    field = fields.String(metadata={"description": "JSON pointer / field name."})
    message = fields.String(metadata={"description": "Human-readable reason."})


class ProblemDetailsSchema(Schema):
    """RFC 9457 problem+json — the single error envelope for the whole API.

    Clients branch on the stable ``type`` URI, never on ``title``/``detail``.
    """

    type = fields.String(
        required=True, metadata={"description": "Stable problem-type URI."}
    )
    title = fields.String(required=True)
    status = fields.Integer(
        required=True, metadata={"description": "Matches the HTTP status code."}
    )
    detail = fields.String()
    instance = fields.String()
    error_class = fields.String(
        metadata={"description": "CLI/pipeline typed-error class, when applicable."}
    )
    errors = fields.List(fields.Nested(ProblemErrorItemSchema))
