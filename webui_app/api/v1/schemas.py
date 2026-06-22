"""marshmallow schemas for ``/api/v1`` — Plan 2026-06-18-002 U1.

These are the request/response DTOs the OpenAPI 3.1 spec is generated from
(apispec ``MarshmallowPlugin``). marshmallow ships with apiflask; it is the
API-edge schema layer and is deliberately separate from the domain's pydantic
models. Wire format is snake_case; timestamps are RFC 3339 UTC; ids are strings.
"""

from __future__ import annotations

from marshmallow import INCLUDE, Schema, fields


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


# ── monitoring aggregate (anomaly-first dashboard) — Plan 2026-06-18-002 U6 ──


class MonitorActionSchema(Schema):
    """An in-place quick action attached to a monitor card (or null)."""

    label = fields.String(required=True)
    href = fields.String(required=True)


class MonitorCardSchema(Schema):
    """One subsystem card. Severity + gap computed server-side (plan R3)."""

    key = fields.String(required=True)
    title = fields.String(required=True)
    severity = fields.String(
        required=True, metadata={"description": "danger | warning | ok | info."}
    )
    headline = fields.String(required=True)
    detail = fields.String(required=True)
    deep_link = fields.String(
        required=True, metadata={"description": "Legacy page to drill into."}
    )
    action = fields.Nested(MonitorActionSchema, allow_none=True)


class MonitorSummarySchema(Schema):
    """Anomaly-first aggregate feed; cards are pre-sorted most-urgent first."""

    cards = fields.List(fields.Nested(MonitorCardSchema), required=True)
    anomaly_count = fields.Integer(
        required=True, metadata={"description": "Count of danger+warning cards."}
    )
    degraded = fields.Boolean(
        required=True, metadata={"description": "True if the aggregator itself failed."}
    )


# ── publish history — Plan 2026-06-18-002 U7 ────────────────────────────────


class HistoryItemSchema(Schema):
    """One publish-history row (events.db, normalised by HistoryAPI)."""

    id = fields.String(required=True)
    target_url = fields.String(required=True)
    created_at = fields.String()
    platform = fields.String()
    status = fields.String(metadata={"description": "published | failed | unknown."})
    article_urls = fields.List(fields.String())
    run_id = fields.String()
    language = fields.String()
    error = fields.String()
    verified_at = fields.Integer(allow_none=True)
    publish_mode = fields.String()
    target_dofollow = fields.String(
        metadata={"description": "dofollow | dofollow_lost | stripped | unverified."}
    )


class HistoryListSchema(Schema):
    """The full history list (object envelope, never a bare array)."""

    items = fields.List(fields.Nested(HistoryItemSchema), required=True)


class HistoryMutationResultSchema(Schema):
    """Result of a history mutation — the refreshed list plus an optional message."""

    items = fields.List(fields.Nested(HistoryItemSchema), required=True)
    message = fields.String()


class HistoryIdRequestSchema(Schema):
    """Single-id mutation body (delete / recheck)."""

    id = fields.String(required=True)


class HistoryIdsRequestSchema(Schema):
    """Multi-id mutation body (bulk-delete)."""

    ids = fields.List(fields.String(), required=True)


# ── draft queue — Plan 2026-06-18-002 U7 ────────────────────────────────────


class DraftItemSchema(Schema):
    """One draft-queue row (drafts_store)."""

    id = fields.String(required=True)
    target_url = fields.String(required=True)
    platform = fields.String()
    language = fields.String()
    publish_mode = fields.String()
    status = fields.String(metadata={"description": "pending | scheduled | published | failed."})
    scheduled_at = fields.String(allow_none=True)
    created_at = fields.String()
    article_urls = fields.List(fields.String())
    error = fields.String(allow_none=True)


class DraftListSchema(Schema):
    items = fields.List(fields.Nested(DraftItemSchema), required=True)


class DraftMutationResultSchema(Schema):
    """Refreshed list + optional message (a warning when a job lingered)."""

    items = fields.List(fields.Nested(DraftItemSchema), required=True)
    message = fields.String()


class DraftIdRequestSchema(Schema):
    id = fields.String(required=True)


class DraftScheduleRequestSchema(Schema):
    id = fields.String(required=True)
    scheduled_at = fields.String(
        required=True, metadata={"description": "ISO-8601 datetime to publish at."}
    )


class DraftIdsRequestSchema(Schema):
    ids = fields.List(fields.String(), required=True)


# ── work-themed sites config — Plan 2026-06-18-002 U7 ───────────────────────


class SiteItemSchema(Schema):
    """One configured site row with live autopilot status (SitesAPI.list_sites)."""

    label = fields.String(required=True)
    main_url = fields.String(required=True)
    autopilot_enabled = fields.Boolean(required=True)
    autopilot_interval = fields.Integer(
        required=True, metadata={"description": "Seconds between autopilot runs."}
    )
    alert_pending = fields.Boolean(required=True)
    next_run_time_iso = fields.String(
        allow_none=True, metadata={"description": "ISO-8601 next autopilot run, or null."}
    )


class SiteListSchema(Schema):
    items = fields.List(fields.Nested(SiteItemSchema), required=True)


class SiteFormSchema(Schema):
    """Edit-prefill payload for an existing site (textarea-joined pools)."""

    main_url = fields.String(required=True)
    list_url = fields.String()
    work_urls = fields.String()
    branded_pool = fields.String()
    partial_pool = fields.String()
    exact_pool = fields.String()
    work_anchor_templates = fields.String()
    count = fields.String()
    insecure_tls = fields.Boolean()


class SiteFormEnvelopeSchema(Schema):
    """``{form: …|null}`` — null when the requested domain is not configured."""

    form = fields.Nested(SiteFormSchema, allow_none=True, required=True)


class SiteWidgetsSchema(Schema):
    """Read-only side panels: plan-gap weekly summary + citation-share alert."""

    plan_gap = fields.Dict(
        required=True, metadata={"description": "status: ok|missing|invalid (+counts)."}
    )
    citation_alert = fields.Dict(
        allow_none=True, metadata={"description": "{ts} when share is low, else null."}
    )


class SiteSaveRequestSchema(Schema):
    """Three-URL config inputs. Blank optional pools are server-derived."""

    main_url = fields.String(
        required=True, metadata={"description": "https + host-root + single trailing slash."}
    )
    list_url = fields.String(load_default="")
    work_urls = fields.String(load_default="", metadata={"description": "Newline-separated."})
    branded_pool = fields.String(load_default="")
    partial_pool = fields.String(load_default="")
    exact_pool = fields.String(load_default="")
    work_anchor_templates = fields.String(load_default="")
    count = fields.String(load_default="10")
    insecure_tls = fields.Boolean(load_default=False)


class SiteSaveResultSchema(Schema):
    """Save outcome + refreshed list. ``autofilled`` names server-derived fields."""

    ok = fields.Boolean(required=True)
    saved_domain = fields.String(required=True)
    autofilled = fields.List(fields.String(), required=True)
    items = fields.List(fields.Nested(SiteItemSchema), required=True)


class SiteAutopilotRequestSchema(Schema):
    site_url = fields.String(required=True)
    enabled = fields.Boolean(required=True)
    interval_seconds = fields.Integer(
        load_default=86400, metadata={"description": "3600 (1h) … 2592000 (30d) when enabled."}
    )


class SiteAutopilotResultSchema(Schema):
    """Autopilot toggle outcome + refreshed list."""

    ok = fields.Boolean(required=True)
    site_url = fields.String(required=True)
    enabled = fields.Boolean(required=True)
    next_run_time = fields.String(allow_none=True)
    last_run = fields.Raw(allow_none=True)
    items = fields.List(fields.Nested(SiteItemSchema), required=True)


class ScrapePreviewSchema(Schema):
    """Work-URL metadata probe. ``status`` is ok|error; fields present on ok only."""

    status = fields.String(required=True, metadata={"description": "ok | error."})
    title = fields.String()
    description = fields.String()
    h1 = fields.String()
    reason = fields.String(metadata={"description": "Failure reason (status=error)."})


# ── settings credential writes (security core) — Plan 2026-06-18-002 U7 ─────


class TokenSaveRequestSchema(Schema):
    """Paste-token save/clear. ``clear=true`` removes the credential file."""

    token = fields.String(metadata={"description": "Secret token (omit when clearing)."})
    clear = fields.Boolean(load_default=False)


class NotionTokenRequestSchema(Schema):
    """Notion credential (two fields), or ``clear=true`` to remove."""

    integration_token = fields.String()
    database_id = fields.String()
    clear = fields.Boolean(load_default=False)


class NotionStatusSchema(Schema):
    """Notion card state. ``configured`` = a token file with an integration_token
    exists; ``database_id`` is the non-secret target database, echoed for display.
    The integration_token itself is NEVER returned."""

    configured = fields.Boolean(required=True)
    database_id = fields.String()


class CredentialResultSchema(Schema):
    """Outcome of a credential write/clear. Never echoes the secret."""

    ok = fields.Boolean(required=True)
    cleared = fields.Boolean()
    message = fields.String()


class ChannelCredentialRequestSchema(Schema):
    """Registry-dispatched channel credential write (the general bind-save).

    The body is heterogeneous — the channel's registered ``auth_type`` selects
    which inputs apply: ``token`` (token), the per-field set (token_fields, e.g.
    ``site`` / ``api_key`` / ``blog_id`` — sent as extra keys), ``blob`` (the
    cookie JSON as a string, for paste_blob), or ``username``+``password``
    (userpass). ``clear=true`` removes the credential file. Extra keys are
    allowed for the dynamic token_fields case.
    """

    class Meta:
        unknown = INCLUDE

    auth_type = fields.String(
        metadata={"description": "Optional; cross-checked against the registry."}
    )
    clear = fields.Boolean(load_default=False)
    token = fields.String(metadata={"description": "token auth_type."})
    blob = fields.String(metadata={"description": "paste_blob: cookie JSON as text."})
    username = fields.String(metadata={"description": "userpass auth_type."})
    password = fields.String(metadata={"description": "userpass auth_type."})


# ── channel browser-bind flow — Plan 2026-06-18-002 U7 ──────────────────────


class BindStartResultSchema(Schema):
    """A launched bind job."""

    job_id = fields.String(required=True)
    channel = fields.String(required=True)
    status = fields.String(required=True, metadata={"description": "Always 'running' on launch."})


class BindPollResultSchema(Schema):
    """Bind-job snapshot. Free-form lifecycle fields (status / events / message)
    surfaced from the job registry; additional keys may appear per phase."""

    class Meta:
        unknown = INCLUDE

    channel = fields.String(required=True)
    status = fields.String(metadata={"description": "running / done / failed / …"})


class BindResolveResultSchema(Schema):
    """Outcome of an identity-mismatch resolution."""

    resolved = fields.String(
        required=True,
        metadata={"description": "keep → kept|expired|noop; replace → replaced."},
    )


class BloggerOAuthRequestSchema(Schema):
    """Blogger Client ID / Secret save. A blank ``client_secret`` preserves the
    stored value (the start→callback OAuth redirect handshake stays legacy)."""

    client_id = fields.String()
    client_secret = fields.String(
        metadata={"description": "Blank preserves the stored secret."}
    )


class LlmConfigRequestSchema(Schema):
    """LLM / image-gen settings save. ``{"action": "clear"}`` resets to defaults.
    Endpoints must be https; blank secrets preserve the stored value; the checkbox
    fields are real JSON booleans. Extra keys (image_gen_*) are allowed."""

    class Meta:
        unknown = INCLUDE

    action = fields.String(metadata={"description": '"clear" resets to defaults.'})
    endpoint = fields.String(metadata={"description": "Must be https:// (or blank)."})
    api_key = fields.String(metadata={"description": "0600 secret; blank preserves stored."})
    model = fields.String()
    temperature = fields.Float()
    system_prompt = fields.String()
    use_article_gen = fields.Boolean()
    article_system_prompt = fields.String()
    use_image_gen = fields.Boolean(
        metadata={"description": "Requires image_gen_endpoint (https) + image_gen_model."}
    )


class LlmConfigViewSchema(Schema):
    """Redaction-safe LLM/image-gen settings for the SPA form to hydrate. The two
    secrets (api_key / image_gen_api_key) are exposed ONLY as ``has_*`` booleans —
    never the key — so a blank submit preserves the stored value."""

    endpoint = fields.String()
    model = fields.String()
    temperature = fields.Float()
    system_prompt = fields.String()
    article_system_prompt = fields.String()
    use_article_gen = fields.Boolean()
    use_image_gen = fields.Boolean()
    image_gen_endpoint = fields.String()
    image_gen_model = fields.String()
    image_gen_banner_size = fields.String()
    has_api_key = fields.Boolean(metadata={"description": "True if a key is stored (the key itself is never returned)."})
    has_image_gen_api_key = fields.Boolean()


class LlmTestConnectionRequestSchema(Schema):
    """Connection probe inputs; blank fields fall back to the stored settings."""

    endpoint = fields.String()
    api_key = fields.String()
    model = fields.String()


class LlmTestGenerationRequestSchema(Schema):
    """Generation-preview input."""

    test_title = fields.String(metadata={"description": "Topic/keyword for the preview."})


class LlmDiagnosticResultSchema(Schema):
    """LLM diagnostic outcome. ``status`` ∈ ok|failed|error is what the client
    branches on (NOT an RFC 9457 problem — a failed test is a successful call that
    reports a failed probe)."""

    status = fields.String(required=True)
    message = fields.String()
    models = fields.List(fields.String())
    result = fields.String()
    reason = fields.String(metadata={"description": "Structured rejection reason on a failed probe."})


class ImageGenGenerateSampleRequestSchema(Schema):
    """Sample-banner generation input. Endpoint/model/token come from config.toml
    [image_gen] — only the (optional) prompt is supplied per request."""

    prompt = fields.String(
        metadata={"description": "Overrides the default banner prompt; blank uses it."}
    )


class ImageGenDiagnosticResultSchema(Schema):
    """Image-gen diagnostic outcome. ``ok`` is what the client branches on (NOT an
    RFC 9457 problem — a failed probe is a successful call that reports a failure).
    The probe (test-connection) and the generation (generate-sample) share this
    envelope; only the populated keys differ."""

    ok = fields.Boolean(required=True)
    error = fields.String(metadata={"description": "Failure reason (probe/generate failed)."})
    # connectivity probe
    model_count = fields.Integer()
    configured_model = fields.String()
    note = fields.String()
    frw_credits_remaining = fields.Float(metadata={"description": "FRW provider credit balance."})
    # sample generation
    data_url = fields.String(metadata={"description": "base64 data-URL of the generated banner."})
    mime = fields.String()
    size_kb = fields.Float()
    prompt = fields.String()
    source_url = fields.String()


class MediumLoginResultSchema(Schema):
    """Medium browser-login action outcome. ``level`` (success|info|warning|danger)
    is what the client branches on (NOT an RFC 9457 problem — a failed launch/probe
    is a successful call reporting an operational result). No request body — the
    launch/probe/clear actions take no inputs."""

    level = fields.String(required=True)
    message = fields.String(required=True)
    logged_in = fields.Boolean(
        allow_none=True,
        metadata={"description": "Resulting publish-gating state; null = unchanged (error)."},
    )


class MediumBrowserStatusSchema(Schema):
    """Medium browser-fallback readiness — filesystem/import read, no secrets.
    ``state`` ∈ not_installed | no_profile | profile_exists_unverified | logged_in."""

    state = fields.String(required=True)
    playwright_installed = fields.Boolean(required=True)
    profile_has_cookies = fields.Boolean(required=True)
    cookies_age_days = fields.Integer(allow_none=True)
    singleton_lock_present = fields.Boolean(required=True)
    logged_in = fields.Boolean(required=True)


class MediumStatusSchema(Schema):
    """GET hydration for the Medium channel card: browser readiness + whether an
    OAuth token file exists (drives the revoke button). No secret values."""

    browser = fields.Nested(MediumBrowserStatusSchema, required=True)
    oauth_token_exists = fields.Boolean(required=True)


class VelogStatusSchema(Schema):
    """Velog channel card status. ``state`` ∈ err | warn | ok | fresh | cap_reached
    | permission_denied. ``cookies_path`` is a local file path (not a secret);
    ``guide`` is the operator remediation hint; ``count``/``cap`` are the daily quota."""

    state = fields.String(required=True)
    label = fields.String(required=True)
    guide = fields.String()
    cookies_path = fields.String()
    count = fields.Integer()
    cap = fields.Integer()


class VelogLoginResultSchema(Schema):
    """Velog-login spawn outcome envelope (always HTTP 200; NOT problem+json — an
    early-died subprocess is a successful call reporting a result). ``error_code``
    is null on success; ``log_path`` is where the detached process keeps writing."""

    ok = fields.Boolean(required=True)
    message = fields.String(required=True)
    error_code = fields.String(allow_none=True)
    log_path = fields.String()


class BloggerStatusSchema(Schema):
    """GET hydration for the Blogger card: authorization state + the saved OAuth
    client. ``client_id`` is the public app id (not a secret); the secret is exposed
    ONLY as ``client_secret_set``. ``callback_uri`` is what to register in Google
    Cloud Console for the Web-application client type."""

    authorized = fields.Boolean(required=True)
    client_id = fields.String()
    client_secret_set = fields.Boolean(required=True)
    callback_uri = fields.String()


class BlogIdsViewSchema(Schema):
    """The domain → Blogger Blog ID routing map (publish-time routing, not a
    secret)."""

    blog_ids = fields.Dict(keys=fields.String(), values=fields.String(), required=True)


class BlogIdsRequestSchema(Schema):
    """Save the domain → Blogger Blog ID mapping. Entries are stripped; blank
    domain/id pairs dropped; a later domain wins on duplicate."""

    blog_ids = fields.Dict(keys=fields.String(), values=fields.String(), required=True)


class KeywordPoolsRequestSchema(Schema):
    """Per-domain SEO anchor keyword pools. Each list holds raw keyword strings;
    the server strips blanks, rejects any keyword >60 chars (422), and de-dups."""

    pools = fields.Dict(
        keys=fields.String(),
        values=fields.List(fields.String()),
        required=True,
        metadata={"description": "{ '<domain>': ['keyword', ...] }"},
    )


class ScheduleSettingsRequestSchema(Schema):
    """Publish-cadence settings. Both are clamped server-side (interval >=0.5h,
    jitter >=0min). Doubles as the GET hydration response."""

    min_interval_hours = fields.Float(metadata={"description": "Min hours between publishes (>=0.5)."})
    jitter_minutes = fields.Integer(metadata={"description": "Random jitter, minutes (>=0)."})


class ChannelOverviewItemSchema(Schema):
    """One WebUI-visible channel's binding status (read-only). ``identity`` is the
    bound account name (not a secret); ``dofollow`` is True/False/"uncertain"."""

    slug = fields.String(required=True)
    display_name = fields.String(required=True)
    auth_type = fields.String(allow_none=True)
    bound = fields.Boolean(required=True)
    identity = fields.String(allow_none=True)
    dofollow = fields.Raw(allow_none=True, metadata={"description": "true | false | \"uncertain\""})
    last_verify_result = fields.String(allow_none=True)
    blockers = fields.List(fields.String())


class ChannelOverviewListSchema(Schema):
    channels = fields.List(fields.Nested(ChannelOverviewItemSchema), required=True)


class BindingFieldSchema(Schema):
    """One input in a channel binding form — presentation metadata only, never a
    value. ``secret`` marks a password input (never pre-filled; blank submit
    preserves the stored secret). ``type`` ∈ text | password | url | textarea."""

    name = fields.String(required=True, metadata={"description": "POST field name (save-path source of truth)."})
    label = fields.String(required=True)
    type = fields.String(required=True, metadata={"description": "text | password | url | textarea"})
    placeholder = fields.String()
    help = fields.String()
    secret = fields.Boolean(required=True)


class ChannelFormSchema(Schema):
    """A fixed-credential channel's binding form: which fields the SPA renders.
    Bind-state (bound/identity) is NOT here — the SPA joins it from the overview."""

    slug = fields.String(required=True)
    display_name = fields.String(required=True)
    auth_type = fields.String(required=True, metadata={"description": "token | token_fields | paste_blob | userpass"})
    supports_clear = fields.Boolean(required=True)
    save_via = fields.String(
        required=True,
        metadata={"description": "credential (generic /credential dispatch) | token (/channels/<ch>/token paste route)"},
    )
    # ``form_fields`` not ``fields`` — the latter shadows marshmallow's Schema.fields.
    form_fields = fields.List(fields.Nested(BindingFieldSchema), required=True, data_key="fields")


class ChannelFormsListSchema(Schema):
    forms = fields.List(fields.Nested(ChannelFormSchema), required=True)


class KeywordPoolsViewSchema(Schema):
    """GET hydration for the keyword-pool editor: the known target domains plus
    each domain's current pool ({domain: [keyword, ...]})."""

    targets = fields.List(fields.String(), required=True,
                          metadata={"description": "Known target domains to show an editor for."})
    pools = fields.Dict(keys=fields.String(), values=fields.List(fields.String()), required=True)


# ── campaign profiles (preset CRUD) — Plan 2026-06-18-002 U7 ────────────────


class ProfileItemSchema(Schema):
    """One saved campaign profile (name-keyed publish preset)."""

    name = fields.String(required=True)
    platform = fields.String()
    language = fields.String()
    url_mode = fields.String()
    publish_mode = fields.String()


class ProfileListSchema(Schema):
    items = fields.List(fields.Nested(ProfileItemSchema), required=True)


class ProfileSaveRequestSchema(Schema):
    name = fields.String(required=True)
    platform = fields.String(load_default="blogger")
    language = fields.String(load_default="zh-CN")
    url_mode = fields.String(load_default="C")
    publish_mode = fields.String(load_default="publish")


class ProfileDeleteRequestSchema(Schema):
    name = fields.String(required=True)


# ── batch campaign creation — Plan 2026-06-18-002 U7 ────────────────────────


class CampaignFormSchema(Schema):
    """Creation-form bootstrap: platforms + connection-state partition (or null)."""

    platforms = fields.List(fields.String(), required=True)
    publish_partition = fields.Dict(
        allow_none=True,
        metadata={"description": "main/extension partition by connection state, or null."},
    )


class CampaignCreateRequestSchema(Schema):
    """Campaign inputs. ``seeds`` is a newline-JSONL string (≤10, each seed_text)."""

    seeds = fields.String(required=True)
    platforms = fields.List(fields.String(), required=True)
    mode = fields.String(load_default="draft", metadata={"description": "draft | publish."})
    cap = fields.String(load_default="", metadata={"description": "Optional per-campaign cap."})
    seed_delay = fields.String(load_default="0")


class CampaignCreateResultSchema(Schema):
    """New campaign id — the SPA navigates to /campaign/<id> progress next."""

    campaign_id = fields.String(required=True)


# ── scheduled drafts (read-only view) — Plan 2026-06-18-002 U7 ───────────────


class ScheduledItemSchema(Schema):
    """One scheduled-draft row (drafts_store, status=scheduled / has scheduled_at)."""

    id = fields.String()
    title = fields.String(metadata={"description": "Article title, or empty."})
    target_url = fields.String()
    platform = fields.String()
    scheduled_at = fields.String(allow_none=True)
    created_at = fields.String()
    status = fields.String()


class ScheduledListSchema(Schema):
    items = fields.List(fields.Nested(ScheduledItemSchema), required=True)


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
