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


# ── pipeline (core publish workbench) — Plan 2026-06-18-002 U5 ───────────────
#
# The /api/v1/pipeline/* endpoints are STATELESS: unlike the legacy /ce:* routes
# (which thread plan/validated state through the Flask ``session``), the SPA holds
# stage state client-side and passes it in each request body. ``plans``/``validated``
# rows are open-ended engine output, so they are documented as free-form objects
# (additionalProperties) rather than pinned field-by-field.


class PlanRequestSchema(Schema):
    """Inputs for plan/generate — mirrors ``build_generate_seed`` (single source)."""

    urls = fields.List(
        fields.String(),
        required=True,
        metadata={"description": "Target URLs; urls[0] is the main URL."},
    )
    platform = fields.String(load_default="blogger")
    url_mode = fields.String(load_default="C")
    publish_mode = fields.String(load_default="publish")
    target_language = fields.String(load_default="zh-CN")
    custom_title = fields.String(load_default="")
    custom_tags = fields.String(load_default="")
    fetch_tdk = fields.String(
        load_default="no",
        metadata={"description": "'yes' fetches TDK for anchor suggestions (network)."},
    )


class PlanResponseSchema(Schema):
    """Generated plan rows (one per article)."""

    plans = fields.List(fields.Dict(), required=True)


class PreviewResponseSchema(Schema):
    """Single-article preview = the first planned row (or null on empty output)."""

    plan = fields.Dict(allow_none=True, required=True)


class ValidateRequestSchema(Schema):
    """Plan rows to validate — accepts a JSONL string or an array of row objects."""

    plans = fields.Raw(
        required=True,
        metadata={"description": "JSONL string or array of plan-row objects."},
    )


class ValidateResponseSchema(Schema):
    """Validated rows (URL checks skipped server-side, mirroring the legacy route)."""

    validated = fields.List(fields.Dict(), required=True)


class PublishRequestSchema(Schema):
    """Publish inputs. ``plans`` is a JSONL string or an array of validated rows."""

    plans = fields.Raw(
        required=True,
        metadata={"description": "JSONL string or array of validated plan rows."},
    )
    platform = fields.String(required=True)
    publish_mode = fields.String(load_default="publish")
    tier_1 = fields.Boolean(
        load_default=False,
        metadata={"description": "Restrict to dofollow Tier-1 platforms only."},
    )
    target_language = fields.String(load_default="zh-CN")
    target_url = fields.String(
        metadata={"description": "Optional hint to enrich history on total failure."}
    )


class PublishResponseSchema(Schema):
    """Aggregate publish result. Total failure is a problem+json, not this schema.

    ``state`` is ``all_success`` or ``partial_success`` (per-row failures are in
    ``results``); the SPA branches on ``state``, not on copy.
    """

    state = fields.String(
        required=True,
        metadata={"description": "all_success | partial_success."},
    )
    n_ok = fields.Integer(required=True)
    n_total = fields.Integer(required=True)
    failure_detail = fields.String(
        metadata={"description": "Joined per-row failure messages (partial_success)."}
    )
    results = fields.List(fields.Dict(), required=True)


class RegenBodyRequestSchema(Schema):
    """Inputs for re-generating one article body via the configured LLM."""

    main_domain = fields.String(required=True)
    anchors = fields.List(fields.String(), required=True)
    language = fields.String(load_default="")
    topic = fields.String(allow_none=True)


class RegenBodyResponseSchema(Schema):
    """Re-generated article body (markdown + rendered HTML) for in-place update."""

    content_markdown = fields.String(required=True)
    content_html = fields.String(required=True)
    content_source = fields.String(required=True)


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
