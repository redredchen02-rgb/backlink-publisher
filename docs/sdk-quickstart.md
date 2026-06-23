# Embeddable SDK — quickstart

> Plan: `docs/plans/2026-06-22-001-refactor-embeddable-sdk-extraction-plan.md`
> Layering: `docs/architecture/sdk-layering.md`

`import backlink_publisher` gives you the whole pipeline in-process — no Flask, no
subprocess, no web server. The three stages return a structured `PipeResult`.

## Scope

Single-operator, **single config per process**, full pipeline. This is *not*
multi-tenant, has no auth layer, and is not published to PyPI — it is an
embeddable in-process library for this repo's own app and scripts. Config is read
from `~/.config/backlink-publisher/` (override with `BACKLINK_PUBLISHER_CONFIG_DIR`).

## The three stages

```python
import backlink_publisher as bp

seeds = [{"target_url": "https://example.com/post", "main_domain": "https://example.com",
          "platform": "blogger", "language": "en"}]

planned = bp.plan(seeds)            # seeds      -> planned backlink rows
if not planned.success:
    raise SystemExit(planned.error)

validated = bp.validate(planned.rows)   # planned rows -> validated rows
if not validated.success:
    raise SystemExit(validated.error)

result = bp.publish(validated.rows)     # validated rows -> published
print(result.success, result.exit_code)
for row in result.rows:
    print(row.get("published_url") or row.get("draft_url"), row.get("status"))
```

Each function accepts a `list[dict]`, a single `dict`, or an already-serialized
JSONL string. `publish` reads `platform` / `publish_mode` from each row (rows are
self-describing).

## `PipeResult`

```python
result.success       # bool — exit_code == 0
result.exit_code     # int  — 0 ok / 2 input / 3 dependency·auth / 4 service / 5 internal
result.error         # str | None — full operator-facing message (never truncated)
result.error_class   # str | None — typed class, e.g. "ExternalServiceError"
result.rows          # list[dict] — parsed JSONL output rows
result.stdout        # str — raw JSONL
```

`publish` keeps the **exit-4-carries-rows** contract: on a partial success
(`exit_code == 4`) `result.success` is `False` but `result.rows` still holds the
rows that published.

## Typed errors

Every error class is exported at the top level and carries an `.exit_code`:

```python
bp.UsageError            # 1
bp.InputValidationError  # 2
bp.DependencyError       # 3   (AuthExpiredError / BannerUploadError / ContentRejectedError are subclasses)
bp.ExternalServiceError  # 4   (AntiBotChallengeError is a subclass)
bp.InternalError         # 5   (RegistryError == 5)
```

Pipeline failures surface through `PipeResult.error_class` / `.exit_code` rather
than raising — branch on those. The exception classes are for code that calls the
lower-level `dispatch` (below) or catches errors from adapters directly.

## Low-level single-payload publish

When you have one fully-constructed payload and want to skip plan→validate:

```python
from backlink_publisher import config
adapter_result = bp.dispatch(payload, "draft", config.load_config())  # -> AdapterResult
```

`bp.dispatch` is the registry's single-payload adapter dispatcher — distinct from
the high-level batch `bp.publish`.

## Browser-tier note

`bp.publish` runs **API-tier** platforms in-process. **Browser-tier** platforms
(`medium`, `velog`, `devto`, `mastodon`) are transparently routed to the
`publish-backlinks` CLI subprocess so a long-lived host process (e.g. Flask) never
spawns Chrome. You don't have to do anything — routing is automatic — but a
browser-tier publish needs the CLI installed on `PATH`.

## Adapters

Adapter registration is explicit and idempotent:

```python
bp.register_all_adapters()
bp.registered_platforms()   # -> ['blogger', 'medium', 'telegraph', …]
```

Importing an adapter module also registers it (import side effect preserved), but
`register_all_adapters()` is the explicit bootstrap.
