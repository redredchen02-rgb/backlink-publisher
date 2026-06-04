# RECON Event Taxonomy

## Overview

The backlink-publisher codebase emits diagnostic and lifecycle events through four distinct transport layers. This document catalogues every event type, its transport, emitter, and typical payload shape.

### Transport layers

| Layer | Format | Destination | Emitter API | Schema prefix |
|---|---|---|---|---|
| **events.db** | JSON via `EventStore.append(kind, payload)` | `~/.cache/backlink-publisher/events.db` (SQLite) | `EventStore.append(kind, payload)` | events/kinds.py |
| **stdout JSONL** | JSONL via `driver._emit(event, **payload)` | stdout (consumed by webui) | `_emit("channel.bind.*", ...)` | channels/__init__.py |
| **stderr recon** | JSON with `"level": "RECON"` via `logger.recon(msg, **extra)` | stderr | `plan_logger.recon(...)`, `publish_logger.recon(...)`, etc. | _util/logger.py |
| **stderr text** | Plain text `RECON info|warn ...` via `print()` | stderr | `_emit_recon_line()` | _plan_check_format.py |

## Event catalogue (70 event names)

### events.db — 18 kind strings

Defined in `events/kinds.py` → `KINDS` frozenset. Written via `EventStore.append()`. **Do NOT rename**: historical rows depend on exact strings.

| Kind | Required floor fields | Emitter |
|---|---|---|
| `publish.intent` | `target_url` | checkpoint reducer |
| `publish.confirmed` | `live_url` | checkpoint/history/drafts reducers |
| `publish.unverified` | `live_url` | publish pipeline |
| `publish.failed` | `error_class`, `error_message_clean` | checkpoint reducer |
| `publish.verified` | `article_id` | (declared-but-dead) |
| `publish.verify_failed` | `article_id`, `error_message` | (declared-but-dead) |
| `draft.created` | `draft_id` | drafts reducer |
| `draft.scheduled` | `draft_id` | drafts reducer |
| `banner.embedded` | `platform` | `banner_dispatcher.py` |
| `banner.failed` | `platform`, `reason` | `banner_dispatcher.py` |
| `banner.skipped_no_method` | `platform` | `banner_dispatcher.py` |
| `banner.skipped_no_artifact` | `platform` | `banner_dispatcher.py` |
| `banner.source_url_fallback` | `platform`, `reason` | `banner_dispatcher.py` |
| `image_gen_invoked` | `prompt_sha` | image-gen pipeline |
| `image_gen_capped` | `reason` | image-gen pipeline |
| `image_gen_disabled_auto` | `threshold` | image-gen pipeline |
| `citation.observed` | `verdict`, `engine`, `query` | probe-citations pipeline |
| `link.rechecked` | `verdict` | recheck-backlinks pipeline |

### stdout JSONL — 5 event names

Defined in `cli/_bind/channels/__init__.py` → `EVENTS` frozenset. Written by `bind-channel` CLI.

| Event | Payload fields | Ordering |
|---|---|---|
| `channel.bind.start` | `channel`, `ts` | 1 |
| `channel.bind.browser_ready` | `channel`, `ts` | 2 |
| `channel.bind.login_detected` | `channel`, `ts` | 3 |
| `channel.bind.persisted` | `channel`, `ts`, `storage_state_path` | 4 |
| `channel.bind.failed` | `channel`, `ts`, `error_code` | any |

### stderr RECON — 46 event names

Emitted via `PipelineLogger.recon()` with `"level": "RECON"`. The `msg` field is the event discriminator.

#### plan.* (13 events) — `cli/plan_backlinks/`

| msg | File | Typical payload |
|---|---|---|
| `link_count_at_plan` | `_engine.py` | branch, count, kinds, main_domain, article_id |
| `cell_gate_summary` | `_engine.py` | enrolled, unrestricted, n_enrolled, n_unrestricted |
| `content_fetch_prefetch` | `_engine.py` | n_urls_prefetched, n_rows |
| `cell_gate_drop` | `_engine.py` | main_domain, platform, line_num, cell |
| `plan_reconciliation` | `_engine.py` | input_rows, output_rows, delta, dropped |
| `content_fetch_stats` | `_engine.py` | per-content-fetch stat keys |
| `preflight_nudge` | `core.py` | distinct_targets, hint |
| `canary_advisory_nudge` | `core.py` | degraded_platforms, hint |
| `fetch_verify_disabled` | `core.py` | reason |
| `category_link_skipped_no_config` | `_links.py` | main_domain, url_mode, reason |
| `detail_link_skipped_no_config` | `_links.py` | main_domain, url_mode, reason |
| `row_dropped_content_gate` | `_links.py` | url, kind, reason |
| `link_dropped_no_content` | `_links.py` | url, kind, reason |
| `target_upgraded_to_threeurl` | `config/parsers/three_url.py` | main, source, n_keywords |

#### validate.* (1 event) — `cli/validate_backlinks.py`

| msg | File | Typical payload |
|---|---|---|
| `validate_reconciliation` | `validate_backlinks.py` | input_rows, output_rows, delta, dropped |

#### publish.* (2 events) — `cli/_publish_helpers.py`

| msg | File | Typical payload |
|---|---|---|
| `publish_reconciliation` | `_publish_helpers.py` | input_payloads, output_rows, delta, dropped |
| `dedup_reconciliation` | `_publish_helpers.py` | skipped_already_published, held_uncertain, dispatched |

#### recheck.* (4 events) — `cli/recheck_backlinks.py`

| msg | File | Typical payload |
|---|---|---|
| `recheck_dry_preview` | `recheck_backlinks.py` | candidates |
| `recheck_skipped_locked` | `recheck_backlinks.py` | (none) |
| `recheck_reconciliation` | `recheck_backlinks.py` | checked, written, *tally |
| `recheck_budget_exhausted` | `recheck_backlinks.py` | probed, deferred |

#### reverify.* (2 events) — `cli/verify_backlinks.py`

| msg | File | Typical payload |
|---|---|---|
| `reverify_dry_preview` | `verify_backlinks.py` | candidates |
| `reverify_reconciliation` | `verify_backlinks.py` | selected, emitted, promoted |

#### probe_citations.* (4 events) — `cli/probe_citations.py`

| msg | File | Typical payload |
|---|---|---|
| `probe_citations_no_pairs` | `probe_citations.py` | (none) |
| `probe_citations_dry_run` | `probe_citations.py` | pairs, cost_ceiling, starvation_risk |
| `probe_citations_skipped_locked` | `probe_citations.py` | (none) |
| `probe_citations_run` | `probe_citations.py` | run_id, engine, probed, site_cited, ... |

#### generate.* (1 event) — `cli/generate_backlink_text.py`

| msg | File | Typical payload |
|---|---|---|
| `generate_summary` | `generate_backlink_text.py` | total, ok, rejected, dry_run |

#### canary.* (5 events) — `cli/canary_targets.py` + `cli/canary_seed.py`

| msg | File | Typical payload |
|---|---|---|
| `canary_summary` | `canary_targets.py` | mode, checked, verdicts, not_configured |
| `canary_coverage_gap` | `canary_targets.py` | platforms, hint |
| `canary_stale_needs_reseed` | `canary_targets.py` | platforms |
| `canary_seed_result` | `canary_seed.py` | platform, verdict, post_url |
| `canary_seed_ambiguous_note` | `canary_seed.py` | reason, hint |

#### preflight.* (2 events) — `cli/preflight_targets.py`

| msg | File | Typical payload |
|---|---|---|
| `preflight_summary` | `preflight_targets.py` | checked, skipped_no_target, verdicts |
| `preflight_unknown_verdict` | `preflight_targets.py` | target, status, reason |

#### cull.* (1 event) — `cli/cull_channels.py`

| msg | File | Typical payload |
|---|---|---|
| `cull_summary` | `cull_channels.py` | total, classifications |

#### click_track.* (1 event) — `cli/click_track.py`

| msg | File | Typical payload |
|---|---|---|
| `click_track_run` | `click_track.py` | targets, property_id, dry_run |

#### comment.* (10 events) — `comment_outreach/`

| msg | File | Typical payload |
|---|---|---|
| `comment_import_skip` | `io_import.py` | row, id, reasons |
| `comment_import_summary` | `io_import.py` | valid, rejected |
| `comment_qualify_skip` | `score.py` | row, id, reasons |
| `comment_qualify_summary` | `score.py` | qualified, rejected, decisions |
| `comment_brief_llm_fallback` | `brief.py` | target_id |
| `comment_brief_skip` | `brief.py` | row, target_id, reasons |
| `comment_brief_summary` | `brief.py` | briefs, skipped, non_accept, provider |
| `comment_discover_skip` | `discover.py` | row, source_url, reasons |
| `comment_discover_summary` | `discover.py` | discovered, rejected, fetched, capped |
| `comment_status_set` | `store.py` | target_id, status, deleted |

### stderr text lines — 2 line shapes

Emitted by `plan-check` via `_plan_check_format.py`.

| Shape | Example |
|---|---|
| `RECON info fetch_head_age_seconds=<n>` | `RECON info fetch_head_age_seconds=300` |
| `RECON warn fetch_skipped reason=<r> fetch_head_age_seconds=<n\|null>` | `RECON warn fetch_skipped reason=offline fetch_head_age_seconds=null` |

## Event name conventions

- **events.db kinds** use dot-separated segments: `domain.action` (e.g. `publish.confirmed`).
- **bind-channel events** use dot-separated segments with `channel.bind` prefix: `channel.bind.start`.
- **stderr RECON** events use snake_case with optional dot or underscore prefixes: `plan_reconciliation`, `probe_citations_run`, `target_upgraded_to_threeurl`.
- **System text lines** use the literal `RECON info|warn` prefix followed by key=value pairs.

## Versioning

This taxonomy is live-updated as new events are added. The companion `event_schema.json` is the authoring-time schema; it is NOT loaded at runtime. The `tests/test_recon_events_against_schema.py` gate statically asserts every `emit("event_name")` and `logger.recon("event_name")` call site has a corresponding `$defs` entry.
