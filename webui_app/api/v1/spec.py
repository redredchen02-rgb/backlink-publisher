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
    DraftIdRequestSchema,
    DraftIdsRequestSchema,
    DraftListSchema,
    DraftMutationResultSchema,
    DraftScheduleRequestSchema,
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
    CampaignCreateRequestSchema,
    CampaignCreateResultSchema,
    CampaignFormSchema,
    BindPollResultSchema,
    BindResolveResultSchema,
    BindStartResultSchema,
    BloggerOAuthRequestSchema,
    ChannelCredentialRequestSchema,
    LlmConfigRequestSchema,
    LlmConfigViewSchema,
    LlmDiagnosticResultSchema,
    LlmTestConnectionRequestSchema,
    LlmTestGenerationRequestSchema,
    ImageGenGenerateSampleRequestSchema,
    ImageGenDiagnosticResultSchema,
    MediumLoginResultSchema,
    MediumStatusSchema,
    VelogStatusSchema,
    VelogLoginResultSchema,
    BloggerStatusSchema,
    BlogIdsViewSchema,
    BlogIdsRequestSchema,
    KeywordPoolsRequestSchema,
    KeywordPoolsViewSchema,
    ChannelOverviewListSchema,
    ChannelFormsListSchema,
    ScheduleSettingsRequestSchema,
    CredentialResultSchema,
    NotionStatusSchema,
    NotionTokenRequestSchema,
    ProfileDeleteRequestSchema,
    ProfileListSchema,
    ProfileSaveRequestSchema,
    ScheduledListSchema,
    TokenSaveRequestSchema,
    ScrapePreviewSchema,
    SiteAutopilotRequestSchema,
    SiteAutopilotResultSchema,
    SiteFormEnvelopeSchema,
    SiteListSchema,
    SiteSaveRequestSchema,
    SiteSaveResultSchema,
    SiteWidgetsSchema,
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
    spec.components.schema("DraftList", schema=DraftListSchema)
    spec.components.schema("DraftMutationResult", schema=DraftMutationResultSchema)
    spec.components.schema("DraftIdRequest", schema=DraftIdRequestSchema)
    spec.components.schema("DraftScheduleRequest", schema=DraftScheduleRequestSchema)
    spec.components.schema("DraftIdsRequest", schema=DraftIdsRequestSchema)
    spec.components.schema("SiteList", schema=SiteListSchema)
    spec.components.schema("SiteFormEnvelope", schema=SiteFormEnvelopeSchema)
    spec.components.schema("SiteWidgets", schema=SiteWidgetsSchema)
    spec.components.schema("SiteSaveRequest", schema=SiteSaveRequestSchema)
    spec.components.schema("SiteSaveResult", schema=SiteSaveResultSchema)
    spec.components.schema("SiteAutopilotRequest", schema=SiteAutopilotRequestSchema)
    spec.components.schema("SiteAutopilotResult", schema=SiteAutopilotResultSchema)
    spec.components.schema("ScrapePreview", schema=ScrapePreviewSchema)
    spec.components.schema("ScheduledList", schema=ScheduledListSchema)
    spec.components.schema("CampaignForm", schema=CampaignFormSchema)
    spec.components.schema("CampaignCreateRequest", schema=CampaignCreateRequestSchema)
    spec.components.schema("CampaignCreateResult", schema=CampaignCreateResultSchema)
    spec.components.schema("ProfileList", schema=ProfileListSchema)
    spec.components.schema("ProfileSaveRequest", schema=ProfileSaveRequestSchema)
    spec.components.schema("ProfileDeleteRequest", schema=ProfileDeleteRequestSchema)
    spec.components.schema("TokenSaveRequest", schema=TokenSaveRequestSchema)
    spec.components.schema("NotionTokenRequest", schema=NotionTokenRequestSchema)
    spec.components.schema("ChannelCredentialRequest", schema=ChannelCredentialRequestSchema)
    spec.components.schema("CredentialResult", schema=CredentialResultSchema)
    spec.components.schema("BindStartResult", schema=BindStartResultSchema)
    spec.components.schema("BindPollResult", schema=BindPollResultSchema)
    spec.components.schema("BindResolveResult", schema=BindResolveResultSchema)
    spec.components.schema("BloggerOAuthRequest", schema=BloggerOAuthRequestSchema)
    spec.components.schema("LlmConfigRequest", schema=LlmConfigRequestSchema)
    spec.components.schema("LlmConfigView", schema=LlmConfigViewSchema)
    spec.components.schema("LlmTestConnectionRequest", schema=LlmTestConnectionRequestSchema)
    spec.components.schema("LlmTestGenerationRequest", schema=LlmTestGenerationRequestSchema)
    spec.components.schema("LlmDiagnosticResult", schema=LlmDiagnosticResultSchema)
    spec.components.schema("ImageGenGenerateSampleRequest", schema=ImageGenGenerateSampleRequestSchema)
    spec.components.schema("ImageGenDiagnosticResult", schema=ImageGenDiagnosticResultSchema)
    spec.components.schema("MediumLoginResult", schema=MediumLoginResultSchema)
    spec.components.schema("MediumStatus", schema=MediumStatusSchema)
    spec.components.schema("VelogStatus", schema=VelogStatusSchema)
    spec.components.schema("VelogLoginResult", schema=VelogLoginResultSchema)
    spec.components.schema("BloggerStatus", schema=BloggerStatusSchema)
    spec.components.schema("NotionStatus", schema=NotionStatusSchema)
    spec.components.schema("BlogIdsView", schema=BlogIdsViewSchema)
    spec.components.schema("BlogIdsRequest", schema=BlogIdsRequestSchema)
    spec.components.schema("KeywordPoolsRequest", schema=KeywordPoolsRequestSchema)
    spec.components.schema("KeywordPoolsView", schema=KeywordPoolsViewSchema)
    spec.components.schema("ChannelOverviewList", schema=ChannelOverviewListSchema)
    spec.components.schema("ChannelFormsList", schema=ChannelFormsListSchema)
    spec.components.schema("ScheduleSettingsRequest", schema=ScheduleSettingsRequestSchema)

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
        path="/api/v1/drafts",
        operations={
            "get": {
                "operationId": "getDrafts",
                "summary": "Full draft-queue list (newest first).",
                "tags": ["drafts"],
                "responses": {"200": _ok("Draft list.", DraftListSchema)},
            }
        },
    )
    spec.path(
        path="/api/v1/drafts/schedule",
        operations={
            "post": {
                "operationId": "scheduleDraft",
                "summary": "Schedule a draft at an ISO-8601 datetime → refreshed list.",
                "tags": ["drafts"],
                "requestBody": _body(DraftScheduleRequestSchema),
                "responses": {
                    "200": _ok("Refreshed list.", DraftMutationResultSchema),
                    "422": _problem_response("Missing/invalid id or datetime."),
                    "502": _problem_response("Persistence failure."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/drafts/publish-now",
        operations={
            "post": {
                "operationId": "publishDraftNow",
                "summary": "Publish a draft now (schedules ~5s out) → refreshed list.",
                "tags": ["drafts"],
                "requestBody": _body(DraftIdRequestSchema),
                "responses": {
                    "200": _ok("Refreshed list.", DraftMutationResultSchema),
                    "422": _problem_response("Missing id."),
                    "502": _problem_response("Persistence failure."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/drafts/cancel",
        operations={
            "post": {
                "operationId": "cancelDraft",
                "summary": "Cancel a scheduled draft (back to pending) → refreshed list.",
                "tags": ["drafts"],
                "requestBody": _body(DraftIdRequestSchema),
                "responses": {
                    "200": _ok("Refreshed list.", DraftMutationResultSchema),
                    "422": _problem_response("Missing id."),
                    "502": _problem_response("Persistence failure."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/drafts/delete",
        operations={
            "post": {
                "operationId": "deleteDraft",
                "summary": "Delete one draft (cancels its job if scheduled) → refreshed list.",
                "tags": ["drafts"],
                "requestBody": _body(DraftIdRequestSchema),
                "responses": {
                    "200": _ok("Refreshed list.", DraftMutationResultSchema),
                    "422": _problem_response("Missing id."),
                    "502": _problem_response("Persistence failure."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/drafts/bulk-delete",
        operations={
            "post": {
                "operationId": "bulkDeleteDrafts",
                "summary": "Delete multiple drafts → refreshed list.",
                "tags": ["drafts"],
                "requestBody": _body(DraftIdsRequestSchema),
                "responses": {
                    "200": _ok("Refreshed list.", DraftMutationResultSchema),
                    "422": _problem_response("Missing ids."),
                    "502": _problem_response("Persistence failure."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/sites",
        operations={
            "get": {
                "operationId": "getSites",
                "summary": "All configured sites with live autopilot status.",
                "tags": ["sites"],
                "responses": {"200": _ok("Site list.", SiteListSchema)},
            }
        },
    )
    spec.path(
        path="/api/v1/sites/widgets",
        operations={
            "get": {
                "operationId": "getSitesWidgets",
                "summary": "Read-only side panels: plan-gap weekly + citation-share alert.",
                "tags": ["sites"],
                "responses": {"200": _ok("Side-panel data.", SiteWidgetsSchema)},
            }
        },
    )
    spec.path(
        path="/api/v1/sites/form",
        operations={
            "get": {
                "operationId": "getSiteForm",
                "summary": "Edit-prefill for an existing site (?domain=), or null.",
                "tags": ["sites"],
                "responses": {"200": _ok("Form prefill (or null).", SiteFormEnvelopeSchema)},
            }
        },
    )
    spec.path(
        path="/api/v1/sites/save",
        operations={
            "post": {
                "operationId": "saveSite",
                "summary": "Validate + derive + persist a three-URL site → refreshed list.",
                "description": (
                    "Blank optional pools/work_urls are server-derived (TDK + sitemap); "
                    "`autofilled` names the derived fields. Validation failure is a 422 "
                    "problem+json carrying per-field `errors[]`."
                ),
                "tags": ["sites"],
                "requestBody": _body(SiteSaveRequestSchema),
                "responses": {
                    "200": _ok("Saved; refreshed list.", SiteSaveResultSchema),
                    "422": _problem_response("Validation failed (see errors[])."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/sites/autopilot",
        operations={
            "post": {
                "operationId": "setSiteAutopilot",
                "summary": "Enable/disable autopilot for a site → refreshed list.",
                "description": (
                    "Interval must be 3600…2592000 when enabling. A scheduler-sync "
                    "failure rolls back the store and returns 502 (nothing persisted)."
                ),
                "tags": ["sites"],
                "requestBody": _body(SiteAutopilotRequestSchema),
                "responses": {
                    "200": _ok("Toggled; refreshed list.", SiteAutopilotResultSchema),
                    "422": _problem_response("Missing site_url or out-of-range interval."),
                    "502": _problem_response("Scheduler sync failed (store rolled back)."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/sites/scrape-preview",
        operations={
            "get": {
                "operationId": "scrapeSitePreview",
                "summary": "Probe a work URL's title/description/h1 for the form helper.",
                "description": (
                    "A fetch/parse failure is a 200 with status='error' (inline hint); "
                    "only a missing `url` query param is a 422."
                ),
                "tags": ["sites"],
                "responses": {
                    "200": _ok("Metadata probe (status=ok|error).", ScrapePreviewSchema),
                    "422": _problem_response("Missing url query param."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/channels/{channel}/token",
        operations={
            "post": {
                "operationId": "saveChannelToken",
                "summary": "Save/clear a paste-token channel credential (0600 file).",
                "description": (
                    "THREAT-3 surface: writes a 0600 secret file. Transport-guarded "
                    "inline — non-loopback Origin/Referer → 403, refused under "
                    "ALLOW_NETWORK=1. `clear:true` removes the file."
                ),
                "tags": ["settings"],
                "parameters": [
                    {"name": "channel", "in": "path", "required": True,
                     "schema": {"type": "string"}},
                ],
                "requestBody": _body(TokenSaveRequestSchema),
                "responses": {
                    "200": _ok("Saved/cleared (or no-op).", CredentialResultSchema),
                    "403": _problem_response("Non-loopback Origin or ALLOW_NETWORK=1."),
                    "422": _problem_response("Unknown channel / not configured."),
                    "502": _problem_response("Credential write failed."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/notion-token",
        operations={
            "post": {
                "operationId": "saveNotionToken",
                "summary": "Save/clear the Notion credential (integration_token + database_id).",
                "description": (
                    "THREAT-3 surface: writes a 0600 secret file. Same transport guards "
                    "as the channel-token endpoint."
                ),
                "tags": ["settings"],
                "requestBody": _body(NotionTokenRequestSchema),
                "responses": {
                    "200": _ok("Saved/cleared.", CredentialResultSchema),
                    "403": _problem_response("Non-loopback Origin or ALLOW_NETWORK=1."),
                    "422": _problem_response("Missing integration_token / database_id."),
                    "502": _problem_response("Credential write failed."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/notion/status",
        operations={
            "get": {
                "operationId": "getNotionStatus",
                "summary": "Notion card state: whether a credential is stored + the database_id.",
                "description": (
                    "Read-only: ``configured`` (a token file with an integration_token "
                    "exists) and the non-secret ``database_id`` for display. The "
                    "integration_token is never returned. No secrets, no guard."
                ),
                "tags": ["settings"],
                "responses": {
                    "200": _ok("Notion credential state.", NotionStatusSchema),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/channels/{channel}/credential",
        operations={
            "post": {
                "operationId": "saveChannelCredential",
                "summary": "Save/clear a registry-dispatched channel credential (0600 file).",
                "description": (
                    "General bind-save: the channel's registered auth_type "
                    "(token / token_fields / paste_blob / userpass / anon) selects "
                    "the inputs. THREAT-3 surface — writes a 0600 secret file; "
                    "transport-guarded inline (non-loopback Origin → 403, refused "
                    "under ALLOW_NETWORK=1). SSRF/paste-blob/hostname validations run "
                    "in the shared facade. `clear:true` removes the file."
                ),
                "tags": ["settings"],
                "parameters": [
                    {"name": "channel", "in": "path", "required": True,
                     "schema": {"type": "string"}},
                ],
                "requestBody": _body(ChannelCredentialRequestSchema),
                "responses": {
                    "200": _ok("Saved/cleared (or no-op).", CredentialResultSchema),
                    "403": _problem_response("Non-loopback Origin or ALLOW_NETWORK=1."),
                    "422": _problem_response("Unknown channel / validation rejected."),
                    "502": _problem_response("Credential write failed."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/channels/{channel}/bind",
        operations={
            "post": {
                "operationId": "startChannelBind",
                "summary": "Launch a browser-login bind job for a channel.",
                "description": (
                    "Refuses (409) while an identity_mismatch is unresolved. "
                    "Loopback-only (peer + Origin); refused under ALLOW_NETWORK=1."
                ),
                "tags": ["settings"],
                "parameters": [
                    {"name": "channel", "in": "path", "required": True,
                     "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": _ok("Job launched.", BindStartResultSchema),
                    "400": _problem_response("Unknown channel / usage error."),
                    "403": _problem_response("Non-loopback peer/Origin or ALLOW_NETWORK=1."),
                    "409": _problem_response("Unresolved identity mismatch."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/channels/{channel}/bind/{job_id}",
        operations={
            "get": {
                "operationId": "pollChannelBind",
                "summary": "Poll a bind job's status + events.",
                "description": "Loopback-only (peer). Channel-scoped — a job_id from another channel 404s.",
                "tags": ["settings"],
                "parameters": [
                    {"name": "channel", "in": "path", "required": True,
                     "schema": {"type": "string"}},
                    {"name": "job_id", "in": "path", "required": True,
                     "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": _ok("Job snapshot.", BindPollResultSchema),
                    "400": _problem_response("Unknown channel."),
                    "404": _problem_response("Unknown job / channel mismatch."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/channels/{channel}/identity-mismatch/keep",
        operations={
            "post": {
                "operationId": "resolveBindKeep",
                "summary": "Keep the previously bound account (restore bound, never destroy).",
                "description": (
                    "Atomic restore: bound → kept; if the stored credential vanished → "
                    "expired (NOT the destructive replace path); state changed under us → noop."
                ),
                "tags": ["settings"],
                "parameters": [
                    {"name": "channel", "in": "path", "required": True,
                     "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": _ok("Resolved (kept/expired/noop).", BindResolveResultSchema),
                    "400": _problem_response("Unknown channel."),
                    "403": _problem_response("Non-loopback peer/Origin or ALLOW_NETWORK=1."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/channels/{channel}/identity-mismatch/replace",
        operations={
            "post": {
                "operationId": "resolveBindReplace",
                "summary": "Accept the new account: wipe artifacts + drop to unbound.",
                "description": "Deletes storage-state + last-account files; operator must re-bind. Loopback-only.",
                "tags": ["settings"],
                "parameters": [
                    {"name": "channel", "in": "path", "required": True,
                     "schema": {"type": "string"}},
                ],
                "responses": {
                    "200": _ok("Resolved (replaced).", BindResolveResultSchema),
                    "400": _problem_response("Unknown channel."),
                    "403": _problem_response("Non-loopback peer/Origin or ALLOW_NETWORK=1."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/blogger-oauth",
        operations={
            "post": {
                "operationId": "saveBloggerOauth",
                "summary": "Save Blogger Client ID / Secret (blank secret preserves stored).",
                "description": (
                    "Credential save only — the OAuth login redirect to Google is a "
                    "separate legacy browser-navigation route (oauth-start)."
                ),
                "tags": ["settings"],
                "requestBody": _body(BloggerOAuthRequestSchema),
                "responses": {
                    "200": _ok("Saved.", CredentialResultSchema),
                    "422": _problem_response("Missing Client ID / Secret."),
                    "502": _problem_response("Config write failed."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/blogger/status",
        operations={
            "get": {
                "operationId": "getBloggerStatus",
                "summary": "Blogger card state: authorization + saved OAuth client.",
                "description": (
                    "Read-only: whether a token is stored, the public client_id, "
                    "client_secret_set boolean (never the secret), and the callback "
                    "URI to register in Google Cloud Console. No secrets, no guard."
                ),
                "tags": ["settings"],
                "responses": {
                    "200": _ok("Blogger authorization + client state.", BloggerStatusSchema),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/blogger/revoke",
        operations={
            "post": {
                "operationId": "revokeBlogger",
                "summary": "Revoke Blogger authorization (delete the stored token file).",
                "description": (
                    "Config/file op (not a 0600 secret write), so same posture as the "
                    "other OAuth writes: no inline guard, Origin-protected at runtime "
                    "by the app-level guard. No request body."
                ),
                "tags": ["settings"],
                "responses": {
                    "200": _ok("Revoked (or already absent).", CredentialResultSchema),
                    "502": _problem_response("Token-file delete failed."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/blogger/blog-ids",
        operations={
            "get": {
                "operationId": "getBlogIds",
                "summary": "The domain → Blogger Blog ID routing map.",
                "description": "Read-only publish-time routing map. Not a secret, no guard.",
                "tags": ["settings"],
                "responses": {
                    "200": _ok("Current blog-ID mapping.", BlogIdsViewSchema),
                },
            },
            "post": {
                "operationId": "saveBlogIds",
                "summary": "Save the domain → Blogger Blog ID mapping.",
                "description": (
                    "Config write (same no-inline-guard posture as the other blogger "
                    "writes). Entries are stripped, blank pairs dropped, duplicate "
                    "domains deduped (later wins). Covered by the app-level guard."
                ),
                "tags": ["settings"],
                "requestBody": _body(BlogIdsRequestSchema),
                "responses": {
                    "200": _ok("Saved.", CredentialResultSchema),
                    "502": _problem_response("Config write failed."),
                },
            },
        },
    )
    spec.path(
        path="/api/v1/settings/llm-config",
        operations={
            "get": {
                "operationId": "getLlmConfig",
                "summary": "Hydrate the LLM/image-gen settings form (redaction-safe).",
                "description": (
                    "Returns the form fields; the two secrets are exposed only as "
                    "has_api_key / has_image_gen_api_key booleans, never the key."
                ),
                "tags": ["settings"],
                "responses": {
                    "200": _ok("Redaction-safe settings view.", LlmConfigViewSchema),
                },
            },
            "post": {
                "operationId": "saveLlmConfig",
                "summary": "Save/clear LLM + image-gen settings (0600 llm-settings.json).",
                "description": (
                    "THREAT-3 surface: writes a 0600 secret file (api_key). "
                    "Transport-guarded inline — non-loopback Origin → 403, refused "
                    "under ALLOW_NETWORK=1. Endpoints must be https; blank secrets "
                    "preserve the stored value; `action:clear` resets to defaults."
                ),
                "tags": ["settings"],
                "requestBody": _body(LlmConfigRequestSchema),
                "responses": {
                    "200": _ok("Saved/cleared.", CredentialResultSchema),
                    "403": _problem_response("Non-loopback Origin or ALLOW_NETWORK=1."),
                    "422": _problem_response("Non-https endpoint / image-gen validation."),
                    "502": _problem_response("Settings write failed."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/llm/test-connection",
        operations={
            "post": {
                "operationId": "testLlmConnection",
                "summary": "Probe the LLM endpoint (SSRF-guarded) + persist last-known health.",
                "description": (
                    "Guards the endpoint URL before sending the api_key; tries /models "
                    "then /chat/completions. Returns the diagnostic envelope (status ∈ "
                    "ok|failed|error), NOT problem+json — a failed probe is a successful "
                    "call. Blank fields fall back to the stored settings."
                ),
                "tags": ["settings"],
                "requestBody": _body(LlmTestConnectionRequestSchema),
                "responses": {
                    "200": _ok("Probe outcome (ok/error).", LlmDiagnosticResultSchema),
                    "400": _ok("Rejected probe (failed: SSRF/invalid).", LlmDiagnosticResultSchema),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/llm/test-generation",
        operations={
            "post": {
                "operationId": "testLlmGeneration",
                "summary": "Generate an article/anchor preview from the stored LLM settings.",
                "tags": ["settings"],
                "requestBody": _body(LlmTestGenerationRequestSchema),
                "responses": {
                    "200": _ok("Generation outcome (ok/error).", LlmDiagnosticResultSchema),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/image-gen/test-connection",
        operations={
            "post": {
                "operationId": "testImageGenConnection",
                "summary": "Probe the configured image-gen endpoint (no generation cost).",
                "description": (
                    "Reads config.toml [image_gen] + the FRW token, then probes the "
                    "provider (OpenAI-compatible /models or FRW /balance). Returns the "
                    "diagnostic envelope (ok=true|false), NOT problem+json — a failed "
                    "probe is a successful call. No request body."
                ),
                "tags": ["settings"],
                "responses": {
                    "200": _ok("Probe outcome (ok=true|false).", ImageGenDiagnosticResultSchema),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/image-gen/generate-sample",
        operations={
            "post": {
                "operationId": "generateImageGenSample",
                "summary": "Generate one real banner from config (costs one API call).",
                "description": (
                    "Generates a real test banner via the configured provider and "
                    "returns it as a base64 data-URL for inline preview. The optional "
                    "`prompt` overrides the default banner prompt. Envelope-only "
                    "(ok=true|false), NOT problem+json."
                ),
                "tags": ["settings"],
                "requestBody": _body(ImageGenGenerateSampleRequestSchema),
                "responses": {
                    "200": _ok("Generation outcome (ok=true|false).", ImageGenDiagnosticResultSchema),
                },
            }
        },
    )
    for _suffix, _op, _summary in (
        ("launch", "launchMediumBrowserLogin", "Open a headed Chromium to log in to Medium."),
        ("probe", "probeMediumBrowserLogin", "Probe Medium login state via Playwright."),
        ("clear", "clearMediumBrowserLogin", "Delete the persistent Medium login profile."),
    ):
        spec.path(
            path=f"/api/v1/settings/medium/{_suffix}-browser-login",
            operations={
                "post": {
                    "operationId": _op,
                    "summary": _summary,
                    "description": (
                        "Spawns an OS browser process / deletes the login profile, so "
                        "transport-guarded inline (non-loopback Origin → 403, refused "
                        "under ALLOW_NETWORK=1). Returns the action envelope (level ∈ "
                        "success|info|warning|danger), NOT problem+json — a failed "
                        "launch/probe is a successful call. No request body."
                    ),
                    "tags": ["settings"],
                    "responses": {
                        "200": _ok("Action outcome.", MediumLoginResultSchema),
                        "403": _problem_response("Non-loopback Origin or ALLOW_NETWORK=1."),
                    },
                }
            },
        )
    spec.path(
        path="/api/v1/settings/medium/status",
        operations={
            "get": {
                "operationId": "getMediumStatus",
                "summary": "Medium channel card state: browser readiness + oauth-token presence.",
                "description": (
                    "Read-only filesystem/import probe (no Playwright launch, no "
                    "network, no secrets). Drives the SPA Medium card's badges and the "
                    "revoke button. No inline guard — the action POSTs keep theirs."
                ),
                "tags": ["settings"],
                "responses": {
                    "200": _ok("Medium browser readiness + oauth-token presence.", MediumStatusSchema),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/velog/status",
        operations={
            "get": {
                "operationId": "getVelogStatus",
                "summary": "Velog channel card status (6 states).",
                "description": "Read-only: cookie freshness + daily quota. No secrets, no guard.",
                "tags": ["settings"],
                "responses": {
                    "200": _ok("Velog channel status.", VelogStatusSchema),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/velog/login",
        operations={
            "post": {
                "operationId": "velogLogin",
                "summary": "Spawn a headed velog-login window in a detached subprocess.",
                "description": (
                    "Spawns an OS browser process, so transport-guarded inline "
                    "(non-loopback Origin → 403, refused under ALLOW_NETWORK=1). Returns "
                    "the {ok, message, error_code, log_path} envelope, NOT problem+json — "
                    "an early-died subprocess is a successful call. No request body."
                ),
                "tags": ["settings"],
                "responses": {
                    "200": _ok("Spawn outcome.", VelogLoginResultSchema),
                    "403": _problem_response("Non-loopback Origin or ALLOW_NETWORK=1."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/channels",
        operations={
            "get": {
                "operationId": "listChannelOverview",
                "summary": "List every WebUI-visible channel with its binding status.",
                "description": (
                    "Read-only: registry − hidden_from_ui composed with each "
                    "channel's offline status (bound/identity/dofollow/blockers). No "
                    "secrets — the per-channel credential writes keep their guards."
                ),
                "tags": ["settings"],
                "responses": {
                    "200": _ok("Channel binding status list.", ChannelOverviewListSchema),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/channels/forms",
        operations={
            "get": {
                "operationId": "listChannelForms",
                "summary": "List the binding-form schema for every fixed-credential channel.",
                "description": (
                    "Static form metadata (which fields to render for token / "
                    "token_fields / paste_blob / userpass channels). No secrets, no "
                    "bind-state — the SPA joins bound/identity from the overview by slug."
                ),
                "tags": ["settings"],
                "responses": {
                    "200": _ok("Per-channel binding-form schemas.", ChannelFormsListSchema),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/settings/keywords",
        operations={
            "get": {
                "operationId": "getKeywordPools",
                "summary": "Hydrate the keyword-pool editor (target domains + pools).",
                "tags": ["settings"],
                "responses": {
                    "200": _ok("Known targets + each domain's current pool.", KeywordPoolsViewSchema),
                },
            },
            "post": {
                "operationId": "saveKeywordPools",
                "summary": "Save the per-domain SEO anchor keyword pools.",
                "description": (
                    "Strips blanks, rejects any keyword >60 chars (422), de-dups "
                    "within a domain, then writes target_anchor_keywords to config."
                ),
                "tags": ["settings"],
                "requestBody": _body(KeywordPoolsRequestSchema),
                "responses": {
                    "200": _ok("Saved (message notes any auto-dedup).", CredentialResultSchema),
                    "422": _problem_response("A keyword exceeds 60 chars."),
                    "502": _problem_response("Config write failed."),
                },
            },
        },
    )
    spec.path(
        path="/api/v1/settings/schedule",
        operations={
            "get": {
                "operationId": "getScheduleSettings",
                "summary": "Hydrate the publish-cadence form.",
                "tags": ["settings"],
                "responses": {
                    "200": _ok("Current min interval / jitter.", ScheduleSettingsRequestSchema),
                },
            },
            "post": {
                "operationId": "saveScheduleSettings",
                "summary": "Save the publish-cadence (min interval / jitter) settings.",
                "description": (
                    "Parses + clamps min_interval_hours (>=0.5) and jitter_minutes "
                    "(>=0), then writes schedule-settings.json."
                ),
                "tags": ["settings"],
                "requestBody": _body(ScheduleSettingsRequestSchema),
                "responses": {
                    "200": _ok("Saved.", CredentialResultSchema),
                    "422": _problem_response("Non-numeric interval / jitter."),
                    "502": _problem_response("Schedule write failed."),
                },
            },
        },
    )
    spec.path(
        path="/api/v1/settings/medium-oauth/clear",
        operations={
            "post": {
                "operationId": "clearMediumOauth",
                "summary": "Revoke a stored Medium OAuth token (delete medium-token.json).",
                "tags": ["settings"],
                "responses": {
                    "200": _ok("Cleared (idempotent).", CredentialResultSchema),
                    "502": _problem_response("Token delete failed."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/profiles",
        operations={
            "get": {
                "operationId": "getProfiles",
                "summary": "All saved campaign profiles (publish presets).",
                "tags": ["profiles"],
                "responses": {"200": _ok("Profile list.", ProfileListSchema)},
            }
        },
    )
    spec.path(
        path="/api/v1/profiles/save",
        operations={
            "post": {
                "operationId": "saveProfile",
                "summary": "Upsert a campaign profile by name → refreshed list.",
                "tags": ["profiles"],
                "requestBody": _body(ProfileSaveRequestSchema),
                "responses": {
                    "200": _ok("Refreshed list.", ProfileListSchema),
                    "422": _problem_response("Missing profile name."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/profiles/delete",
        operations={
            "post": {
                "operationId": "deleteProfile",
                "summary": "Delete a campaign profile by name → refreshed list.",
                "tags": ["profiles"],
                "requestBody": _body(ProfileDeleteRequestSchema),
                "responses": {
                    "200": _ok("Refreshed list.", ProfileListSchema),
                    "422": _problem_response("Missing profile name."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/campaigns/form",
        operations={
            "get": {
                "operationId": "getCampaignForm",
                "summary": "Creation-form bootstrap: platforms + connection partition.",
                "tags": ["campaigns"],
                "responses": {"200": _ok("Form bootstrap.", CampaignFormSchema)},
            }
        },
    )
    spec.path(
        path="/api/v1/campaigns",
        operations={
            "post": {
                "operationId": "createCampaign",
                "summary": "Validate + create a batch campaign → {campaign_id}.",
                "description": (
                    "Seeds is a newline-JSONL string (≤10, each with seed_text). "
                    "Validation failure is a 422 problem+json with per-field errors[]. "
                    "On success the SPA navigates to /campaign/<id> progress."
                ),
                "tags": ["campaigns"],
                "requestBody": _body(CampaignCreateRequestSchema),
                "responses": {
                    "200": _ok("Created.", CampaignCreateResultSchema),
                    "422": _problem_response("Validation failed (see errors[])."),
                },
            }
        },
    )
    spec.path(
        path="/api/v1/schedule",
        operations={
            "get": {
                "operationId": "getSchedule",
                "summary": "Drafts scheduled for future publish (read-only view).",
                "description": "Fail-soft: a query failure degrades to an empty list.",
                "tags": ["schedule"],
                "responses": {"200": _ok("Scheduled draft list.", ScheduledListSchema)},
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
