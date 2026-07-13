# Recipe: adding a new publisher adapter

> Moved verbatim from `AGENTS.md` on 2026-07-13 (condensation pass). The hard invariants
> stay summarized in `AGENTS.md → Adding a new publisher adapter`; this file is the full
> step-by-step recipe, including the banner-embedding contract.

Post-R9, a new platform is one `register("x", XAdapter)` call away from reaching both the CLI argparse layer and `schema.validate_publish_payload`. The dispatcher, schema enum, throttle gating, and LinkedIn-style rejection all read from `publishing.registry.registered_platforms()` — you do not edit any CLI file or `schema.py` to add a new platform.

## 1. Subclass `Publisher`

Reference: `src/backlink_publisher/publishing/adapters/blogger_api.py::BloggerAPIAdapter`.

```python
# src/backlink_publisher/publishing/adapters/yourplatform.py
from typing import Any

from backlink_publisher.config import Config
from backlink_publisher._util.errors import DependencyError, ExternalServiceError
from backlink_publisher.publishing.registry import Publisher
from .base import AdapterResult

class YourPlatformAdapter(Publisher):
    @classmethod
    def available(cls, config: Config) -> bool:
        return True

    def publish(self, payload: dict[str, Any], mode: str, config: Config) -> AdapterResult:
        ...
```

## 2. Implement `publish()`

- Call `extract_publish_html(payload, "yourplatform")` from `publishing.content_negotiation`
- Wrap remote calls in `retry_transient_call` from `.retry` for 429/5xx backoff
- Return `AdapterResult(status="drafted"|"published", ...)`
- Set `post_publish_delay_seconds=N` for rate-limit avoidance
- Raise `DependencyError` (falls through to next adapter) or `ExternalServiceError` (propagates immediately)

## 3. Register

Add one line to `src/backlink_publisher/publishing/adapters/__init__.py`:

```python
from .yourplatform import YourPlatformAdapter
register("yourplatform", YourPlatformAdapter, dofollow=True)
```

`dofollow=` is a **required** keyword argument (Plan 2026-05-20-009). Legal values are `True`, `False`, or `"uncertain"`. Anything other than `True` additionally requires `rationale=` of ≥80 stripped chars explaining why a non-dofollow platform is shipping (mirrors `monolith_budget.toml` rationale discipline; length-only — content is reviewer concern). The gate is enforced at import time (missing `dofollow=` raises `TypeError`) and at CI time by `tests/test_adapter_dofollow_gate.py`.

## 3b. Declare manifest metadata (Plan 2026-05-25-002)

The same `register()` call accepts four optional declarative kwargs that collapse channel-specific wiring across `binding_status.py`, `webui_app/__init__.py`, `helpers/contexts.py`, and templates into a single SSoT. Reference: the **Velog pilot** at `adapters/__init__.py` (lines starting `register("velog", ...)`).

```python
from .._manifest_types import BindDescriptor, Policy, UiMeta

register(
    "yourplatform",
    YourPlatformAdapter,
    dofollow=True,
    ui=UiMeta(
        display_name="Your Platform",         # used by inject_platforms
        domain="yourplatform.com",
        category="dev-blog",                  # or "social", "wiki", ...
        icon="bi-globe2",                     # Bootstrap icon name
    ),
    bind=[
        BindDescriptor(
            backend="token-paste",            # or "cookie", "oauth", "chrome", "cdp"
            storage_state_path="<config_dir>/yourplatform-token.json",
            login_endpoint="/api/yourplatform/login",  # if applicable
            card_template="_settings_channel_yourplatform.html",  # under webui_app/templates/
            extras={                          # escape hatch for platform-specific paths
                "browser_recipe": "backlink_publisher.publishing.browser_publish.recipes.yourplatform",
            },
        ),
    ],
    policy=Policy(
        throttle_band=(60, 180),              # tuple[int, int] seconds
        env_keys={"min": "YOURPLATFORM_THROTTLE_MIN",
                  "max": "YOURPLATFORM_THROTTLE_MAX"},
        retry_id="default",
        liveness_probe_sec=900,
        language_whitelist=("en", "ko"),      # () = no restriction
    ),
    visibility="active",                      # default; or "experimental" / "hidden" / "retired"
)
```

**Why bother**:
- `inject_platforms()` automatically picks up `display_name` from `UiMeta` (no template edit)
- `hidden_from_ui()` / `_settings_context.dashboard_channels` filter automatically via `visibility="hidden"` / `"retired"` (no second wire site)
- `tests/test_manifest_contract.py` validates the manifest shape on every CI run and prints a migration progress board

**`visibility` lifecycle**:

| state | behaviour |
|---|---|
| `"active"` | default; listed everywhere |
| `"experimental"` | opt-in only (CLI `--include-experimental`, WebUI advanced mode) |
| `"hidden"` | UI suppressed; existing bound configs still work (PR #136 write.as pattern) |
| `"retired"` | UI suppressed + `save_config` stops round-tripping its TOML sections (Unit 2b — pending) |

**All four kwargs are optional**. Omitting them is the "legacy" path — channel still registers, but won't benefit from the reverse-lookup wiring. `tests/test_manifest_contract.py` prints `legacy_platforms()` count to surface migration progress.

If the platform name appears in `publishing.registry._REJECTED_PLATFORMS` (the negative-knowledge map seeded from PR #108→#109's `devto` / `mastodon` / `wordpresscom` reverts), `register()` raises `RegistryError` at import time. Un-rejection path: delete the entry from `_REJECTED_PLATFORMS` in the same PR as the new `register()` call — the deletion diff makes the un-rejection visible to reviewers; no `accept_rejection_override` kwarg exists.

Do NOT edit:
- `cli/publish_backlinks/__init__.py` (reads `registered_platforms()` dynamically)
- `cli/plan_backlinks.py` `--default-platform` choices
- `cli/validate_backlinks.py` unsupported-platform rejection
- `schema.py` `supported_platforms()` or `reject_unsupported_platform()`

For fallback chains (like Medium's `APIAdapter → BraveAdapter → BrowserAdapter`), pass all classes in one `register()` call.

## 4. Add config (if needed)

Follow `BloggerOAuthConfig` pattern: frozen dataclass → `Config` field → TOML key → loader path → token helpers.

## 5. Add an optional dependency (if needed)

```toml
[project.optional-dependencies]
yourplatform = ["yourplatform-sdk>=2.0"]
```

## 6. Add tests

Minimum: happy-path mock test, `DependencyError` test, `ExternalServiceError` test. XSS contract test required if adding a `ROUTE_TIER_MATRIX["yourplatform"] = "a"` entry.

The R9 proof in `tests/test_r9_extension_readiness.py` already exercises cross-layer wiring — registering is sufficient to inherit it.

## PR checklist

- [ ] Adapter file under `src/backlink_publisher/publishing/adapters/`
- [ ] One-line `register(...)` in `adapters/__init__.py`
- [ ] Config dataclass / loader / TOML example (if needed)
- [ ] `pyproject.toml` optional-dependency entry (if needed)
- [ ] 3+ adapter tests (happy / DependencyError / ExternalServiceError)
- [ ] XSS contract test (if tier-`"a"` entry added)
- [ ] `README.md` Prerequisites updated
- [ ] `git diff --stat src/backlink_publisher/cli/ src/backlink_publisher/schema.py` is empty

Related: `docs/plans/2026-05-18-009-refactor-cli-extension-readiness-plan.md` (the R9 plan that made this recipe possible), `src/backlink_publisher/publishing/registry.py` (the `Publisher` ABC and dispatcher).

# Adding banner embedding to an adapter

When `Config.image_gen` is set, `plan-backlinks` produces a `banner` dict per row containing `{path, alt, mime, sha, source_url}` (`source_url` added in Plan 2026-05-20-004 Unit 1 R12; rows produced before that treat the missing key as `None`). To get that banner onto the platform's own CDN at publish time (so the embedded URL survives the upstream image-gen CDN's TTL), an adapter opts in by defining `embed_banner(self, artifact_path: Path, alt: str) -> str | None`. The dispatcher (`publishing.banner_dispatcher.apply`, called from `publishing.registry.dispatch` when the caller passes `banner_emit=...`) checks `hasattr(adapter, "embed_banner")` — no registration, no protocol class — and:

- Returns the platform-hosted URL on success → dispatcher prepends `![alt](platform_url)\n\n` to `payload["content_markdown"]` before `adapter.publish()` runs. Emits `banner.embedded`.
- Returns `None` → dispatcher falls back to `banner["source_url"]` (when truthy). Emits `banner.source_url_fallback` with `reason="adapter_returned_none"`. If `source_url` is also missing (b64-only provider OR pre-R12 row), the banner is silently omitted with `banner.skipped_no_artifact`.
- Raises `BannerUploadError` → handled by `config.image_gen.strict`: `false` (default) logs warn and publishes without the banner (emits `banner.failed`); `true` propagates out of `dispatch()` and the publish loop records a row-level `error_class="banner_upload"` checkpoint (the run continues with the next row, NOT exit-3 like other DependencyError families).
- Raises non-`BannerUploadError` (adapter bug) → propagates unconditionally, even when `strict=False`. Strict gating governs only banner-specific failures, never adapter implementation bugs.

Adapters that don't define `embed_banner` are handled by the same dispatcher: `source_url` is prepended via the not-opted-in branch, emitting `banner.source_url_fallback` with `reason="adapter_no_method"`. If no `source_url` either, emits `banner.skipped_no_method` and the body is unchanged.

Per-platform upload contract:
- **telegraph**: `POST https://telegra.ph/upload` with raw bytes; returns `telegra.ph/file/<sha>.<ext>` URL.
- **velog**: `image_upload_url` GraphQL mutation returns a presigned URL → PUT bytes.
- **ghpages**: commit the file to `<repo>/assets/banners/<sha>.<ext>` and return the `raw.githubusercontent.com` URL.
- **blogger**: data-URI base64 inline (probe-confirmed at Unit 3 time) or the legacy `images.insert` backdoor if still alive.

**Medium does NOT implement `embed_banner`.** All three Medium fallback adapters omit the method so the dispatcher prepends `![alt](source_url)`; Medium's publish-time auto-rehost then snapshots the upstream CDN URL into Medium's own image hosting. **Verification required at implementer time**: confirm Medium auto-rehost still works by publishing one row to a scratch account and inspecting the rendered `<img src>`. If auto-rehost is dead, Medium needs its own upload path or banners must be explicitly disabled for Medium.

Error classes: `BannerUploadError(DependencyError)` — raised by per-adapter `embed_banner` implementations on media-API failure. NOT a credential failure; channel-status `mark_expired` must NOT fire on it. Strict-mode propagation lands a row-level checkpoint with `error_class="banner_upload"` — distinct from `AuthExpiredError`'s `error_class="auth_expired"`.

Reference: Plan 2026-05-20-001 Units 1-6 + Plan 2026-05-20-004 Unit 1 + `src/backlink_publisher/publishing/adapters/image_gen/` for the artifact contract.
