---
date: 2026-06-02
type: feat
topic: batch-optimization
status: parked
origin: workspace-root (canonical-repo external)
archived_by: plan 2026-06-10-001 (docs consolidation)
notes: awaiting convergence review against existing batch implementation
---

# Batch Optimization Plan

> Batch spray-backlinks multi-seed support + WebUI campaign management.
> Based on requirements doc reviewed by 6 parallel reviewers (coherence, feasibility, product-lens, design-lens, scope-guardian, adversarial). Synthesis findings incorporated as resolved decisions below.

## Problem Frame

Operators currently run 1-5 seeds × 3-5 platforms in serial. `spray-backlinks` accepts exactly one seed (`len(rows) != 1` → UsageError). WebUI `/ce:batch` is single-platform only. No campaign-level management view exists.

**Scale**: ~5-25 published articles per batch. Frequency: ~1-3 batches per day per operator.

The reviewed requirements identified multiple gaps that the original assumptions didn't cover. The plan below resolves them explicitly rather than inheriting unchecked assumptions.

### Key Review Resolutions

| Review Finding | Resolution |
|---|---|
| P0: bulk_publish_now doesn't exist | U2 implements it — explicitly build, not assume |
| P0: R7 async contradicts "no background service" | Accept a dedicated ThreadPoolExecutor for campaign execution. Remove "no new background service" constraint for campaigns. Existing APScheduler (max_workers=1) remains for single-task scheduling |
| P1: No campaign data model | U1 defines CampaignStore — new store, not extending queue_store |
| P1: No navigation model | Campaign tab added to existing WebUI navbar — extend, not replace |
| P1: Draft review duplicates existing | U6 extends existing draft UI with campaign_id filter instead of building new /batch-review page |
| P1: Missing per-seed failure semantics | Per-seed isolation: each seed fails independently, campaign continues, errors collected into summary |
| P1: Missing polling contract | GET /api/campaign/<id>/status with defined response schema (U5) |
| P2: CLI shell wrapper as alternative | Evaluated: inadequate for WebUI integration; R1-R5 still needed for programmatic multi-seed |
| P2: Jitter default too aggressive | Changed default seed-delay from 60-180s to 15-60s. Jitter is opt-in configurable via --seed-delay, not on by default |

## Scope Boundaries

**In scope:**
- CLI multi-seed spray (extend existing spray-backlinks, no new CLI)
- WebUI campaign creation page (one page, not a full dashboard)
- Campaign execution via dedicated worker pool (not APScheduler)
- Draft review for campaigns (extend existing interface, not new page)
- CampaignStore for state persistence (new store, not queue_store extension)
- Per-seed independent processing with configurable inter-seed delay

**Deferred to follow-up:**
- Campaign history / listing dashboard — U5's result view is per-campaign only; a cross-campaign history view is deferred
- Campaign templates / seed library — deferred per original requirements
- Scheduled campaign execution — deferred per original requirements
- Parallel platform publishing (concurrent seeds) — deferred; remaining serial for now

**Explicitly not in scope:**
- Modifying publish-backlinks core logic
- New background service process (in-process worker pool is acceptable)
- Full campaign management dashboard (Phase 2 potential after usage data)

## Summary

Delivers multi-seed campaign capability across CLI and WebUI. CLI changes are minimal (remove single-seed guard, add loop + delay). WebUI changes add a campaign creation page, campaign execution via background worker, and campaign-scoped draft review extending the existing draft interface. A new CampaignStore handles campaign-level state — not the existing queue_store, which is unsuited for this purpose.

---

## Key Technical Decisions

### Decision 1: CampaignWorker — dedicated in-process worker pool

**Context**: R7 requires non-blocking campaign execution. The existing APScheduler has `max_workers=1` and is designed for individual publish jobs (~5s). A 5-seed × 5-platform campaign takes 12-50 minutes.

**Choice**: Create a `CampaignWorker` class with its own `ThreadPoolExecutor(max_workers=2)` in `webui_app/campaign_worker.py`. This runs alongside APScheduler without interfering. Campaigns execute sequentially within the worker (one at a time), but don't block the APScheduler pool.

**Trade-off**: Accepts the "new background execution mechanism" that the original requirements tried to avoid. Justified because the existing scheduler literally cannot handle campaign-scale work without starving other tasks.

### Decision 2: CampaignStore — new store, not queue_store extension

**Context**: R8 assumed queue_store could handle campaign persistence. queue_store schema is flat (id/status/next_retry_at/error) — no campaign_id, per-seed sub-status, progress, or result aggregation.

**Choice**: Create `webui_store/campaign_store.py` with CampaignStore class. Schema supports: campaign_id, seed_rows, selected_platforms, mode, per-seed status tracking (idle/processing/success/failed/skipped), progress percentage, overall campaign status (pending/running/draft_review/completed/failed), timestamps, and result summary.

**Trade-off**: More code than extending queue_store, but cleaner separation of concerns. queue_store remains for single-task scheduling; CampaignStore for aggregate workflows.

### Decision 3: Extend existing draft UI (not new /batch-review page)

**Context**: R10-R13 proposed a new `/batch-review/<campaign_id>` page. Review found the existing draft interface + drafts_store could be extended with campaign_id filtering.

**Choice**: Add campaign_id filter to the existing draft review tab on index.html. DraftsStore gets a `get_by_campaign_id(campaign_id)` query method. The existing "草稿&历史" tab already shows drafts with approve/reject UI — campaign drafts appear there filtered by campaign. No new page, no new routing, no new JS surface.

**Trade-off**: Loses the dedicated campaign-focused review UX. Operators navigate from campaign result view → existing draft tab (pre-filtered). Acceptable because this is <20% of the effort of a new page and can be upgraded later if usage data justifies it.

### Decision 4: Seed-level jitter reduced, opt-in by default

**Context**: R3 proposed 60-180s seed-delay default. Review found no evidence this prevents platform detection.

**Choice**: Default seed-delay = 0 (no forced inter-seed delay). Add `--seed-delay-min` / `--seed-delay-max` flags (range 1-300s) as opt-in. Operators who observe detection patterns can enable jitter. Default behavior: seeds execute sequentially without artificial delay — same as the existing manual loop behavior but automated.

**Trade-off**: Operators who need anti-detection timing must configure it explicitly. Opposite of the original design (jitter on by default, opt-out). Justified because (a) no evidence jitter is necessary, (b) forced delay contradicts the latency improvement goal, (c) configurable is better than wrong-default.

### Decision 5: Per-seed isolation, continue-on-fail

**Context**: Seed 3 of 5 fails. Does the campaign abort or continue?

**Choice**: Each seed is independently processed. Failure of seed N does not affect seeds N+1. The merged JSONL output includes a `seed_id` field per row plus an `error` entry for failed seeds. The campaign result view shows per-seed success/fail breakdown. No automatic retry in v1.

**Trade-off**: Simpler implementation. Retry-from-failure is deferred to follow-up.

---

## Implementation Units

### U1. CampaignStore — campaign state persistence

**Goal**: Create a new store for campaign-level state, separate from the existing queue_store

**Requirements**: R8 (campaign persistence), R7 (progress polling), R9 (result summary)

**Dependencies**: None

**Files**:
- Create: `webui_store/campaign_store.py`
- Modify: `webui_store/__init__.py` (export CampaignStore)
- Test: `tests/test_campaign_store.py`

**Approach**:
- JSON file store (following drafts_store pattern), stored in campaign data directory under config dir
- Schema per campaign:
  ```python
  {
      "campaign_id": str(uuid),
      "status": "pending|running|draft_review|completed|failed",
      "mode": "draft|publish",
      "platforms": ["blogger", "medium", ...],
      "cap": int | None,
      "created_at": ISO timestamp,
      "updated_at": ISO timestamp,
      "seeds": [
          {
              "seed_index": int,
              "seed_text": str,
              "status": "idle|processing|success|failed|skipped",
              "error": str | None,
              "draft_count": int,
              "published_count": int,
          }
      ],
      "progress_pct": float (0-100),
      "result_summary": {
          "total_seeds": int,
          "successful_seeds": int,
          "failed_seeds": int,
          "total_drafts": int,
          "platform_breakdown": {platform: {success: int, failed: int}}
      } | None
  }
  ```
- Methods: `create(campaign_data)`, `get(campaign_id)`, `update_status(campaign_id, updates)`, `update_seed_status(campaign_id, index, updates)`, `list()` (all campaigns, sorted by created_at desc)
- Store reader lock for concurrent access (campaign worker reads, polling endpoint reads)

**Patterns to follow**: drafts_store in `webui_store/drafts.py` — same JSON file persistence pattern, same thread safety approach

**Test scenarios**:
- Create campaign returns valid campaign_id with pending status
- Get campaign by ID returns full schema
- Update status propagates correctly
- Update per-seed status updates progress_pct automatically
- List returns campaigns sorted by created_at desc
- Concurrent read/write does not corrupt data
- Persists across process restart (read back after store reload)

**Verification**: `pytest tests/test_campaign_store.py` green; inspect JSON file on disk for correct schema

---

### U2. DraftsStore.bulk_publish_now — implement the missing publish method

**Goal**: Implement `bulk_publish_now` on DraftsStore. This was incorrectly assumed to exist. Must be built.

**Requirements**: R12 (batch publish), R13 (Publish Approved button)

**Dependencies**: U1 (CampaignStore for campaign_id tracking)

**Files**:
- Modify: `webui_store/drafts.py` (add bulk_publish_now method)
- Test: `tests/test_drafts_store.py` (add test cases)

**Approach**:
- New method `bulk_publish_now(campaign_id, draft_ids)`:
  1. Accept list of draft IDs (pre-filtered by campaign)
  2. For each draft, pipe through existing `adapter_publish` seam (same as `publish-backlinks` per-item path)
  3. Update each draft's status to `published` after success, `failed` on error
  4. Update CampaignStore per-draft counts
  5. Return `{published: int, failed: int, errors: [str]}`
- Do NOT use APScheduler for this publish path (campaign drafts publish synchronously within the campaign context)
- The method is scoped to campaign drafts only — existing pipeline drafts retain their scheduling-based publish path

**Patterns to follow**: existing `DraftAPI.bulk_publish_now` in `webui_app/api/drafts_api.py` for inspiration, but implement it directly on the store layer without APScheduler indirection

**Test scenarios**:
- `bulk_publish_now` with valid draft IDs publishes all and returns success count
- `bulk_publish_now` with mix of valid/invalid IDs reports partial failure
- `bulk_publish_now` with empty list returns 0 published (no-op)
- Draft status correctly transitions to `published` on success
- CampaignStore per-seed counts are updated after publish

**Verification**: `pytest tests/test_drafts_store.py` includes new tests; manual test via WebUI campaign publish flow

---

### U3. spray-backlinks multi-seed CLI (R1-R5)

**Goal**: Extend `spray-backlinks` to accept multiple seeds. Each seed processed independently.

**Requirements**: R1-R5 (multi-seed input, max-seeds cap, per-seed processing, merged JSONL output)

**Dependencies**: U1 (CampaignStore referenced — CLI path uses CampaignStore if running as campaign, or standalone mode without it)

**Files**:
- Modify: `cli/spray_backlinks/core.py` (remove single-seed guard, add multi-seed loop)
- Modify: `cli/spray_backlinks/__init__.py` (update docstring + add --max-seeds, --seed-delay flags)
- Test: `tests/test_spray_backlinks.py` (add multi-seed test cases)

**Approach**:
- Core loop change:
  1. Read all rows from stdin (was: assert exactly 1 row)
  2. Validate: if len(rows) > --max-seeds (default 10), exit 2 with error message
  3. For each row in rows:
     - If running as standalone (no campaign_id): process independently, merge output
     - If running as campaign (campaign_id provided): update CampaignStore per-seed status before/after
  4. Output: merged JSONL to stdout (each row augmented with `seed_id` field)
  5. Stderr: per-seed summary line (seed_index, candidates, drafts, successes, errors)
  - Inter-seed delay: if `--seed-delay-min / --seed-delay-max` set, sleep uniform random between them before processing next seed. Default: no delay
- `expand_seed`, `gate_candidates`, `draft_row`, `dispatch_burst` — unchanged, called once per seed as before
- The existing `len(rows) != 1` check changes to `len(rows) == 0` (error: no input)

**Backward compatibility**: Single-row input produces identical output format (plus `seed_id: 0` field). All existing callers (WebUI /ce:batch, scripts, tests) continue to work because they pipe single rows.

**Patterns to follow**: existing per-seed processing in `cli/spray_backlinks/core.py` — the per-seed loop is the same logic; just add an outer loop

**Test scenarios**:
- Single seed input produces identical output to current behavior (plus seed_id field)
- 5 seeds × 2 platforms produces 10 output rows, each with correct seed_id
- --max-seeds limit respected: 11 rows with default 10 exits 2 with error
- Per-seed failure isolation: seed 2 of 3 fails, output contains results for seeds 0, 1, 3
- --seed-delay config respected (total duration >= (N-1) * min delay)
- Zero rows input exits 2 with usage error
- Merged JSONL includes seed_id field in every row

**Verification**: `pytest tests/test_spray_backlinks.py` green; manual CLI test: `cat seeds.jsonl | spray-backlinks --max-seeds 5` produces correct output

---

### U4. WebUI campaign creation page (R6)

**Goal**: Add `/batch-campaign` page for uploading seeds, selecting platforms, choosing mode

**Requirements**: R6 (campaign creation UI), plus navigation model

**Dependencies**: U1 (CampaignStore), U3 (spray-backlinks multi-seed)

**Files**:
- Create: `webui_app/routes/batch_campaign.py` (new blueprint)
- Create: `webui_app/templates/batch_campaign.html` (campaign creation form)
- Modify: `webui_app/routes/__init__.py` (register blueprint)
- Modify: `webui_app/templates/base.html` or `webui_app/templates/index.html` (add campaign tab to nav)
- Test: `tests/test_webui_routes.py` (add route tests)

**Approach**:
- Campaign creation form:
  - File upload or textarea for seed JSONL (multi-line, one seed per line)
  - Platform multi-select checkboxes (reuse existing platform list from adapter registry)
  - Mode toggle: draft / publish
  - Cap setting (optional, default None)
  - Seed delay toggle: "No delay (default)" / "Custom delay (15-300s)" with range input
- Navigation: add "批量任务" tab to navbar alongside existing "批量" tab. Clicking opens /batch-campaign
- On submit:
  1. Parse and validate JSONL input (client-side + server-side)
  2. Create CampaignStore entry with status "pending"
  3. Submit campaign to CampaignWorker (U5)
  4. Redirect to campaign progress page (/campaign/<id>)
- Form validation:
  - Minimum 1 seed, maximum --max-seeds (default 10)
  - At least 1 platform selected
  - JSONL parseable (try/except on each line)
  - Cap must be positive int or null
- Client-side: validate JSONL parseability before submit; show inline error for malformed lines

**Patterns to follow**: existing `/ce:batch` route pattern, platform list from adapter_registry (reuse existing logic), form styling from existing templates

**Test scenarios**:
- GET /batch-campaign returns 200 with form
- POST with valid 5-seed JSONL + 2 platforms creates campaign, returns 302 to /campaign/<id>
- POST with empty seed input returns form validation error
- POST with 0 platforms selected returns form validation error
- POST with malformed JSONL returns parse error per row
- POST with 11 seeds (default max=10) returns cap error
- New "批量任务" tab visible in navbar
- Campaign appears in CampaignStore after creation

**Verification**: `pytest tests/test_webui_routes.py` green; manual: navigate to /batch-campaign, submit form, verify redirect to progress page

---

### U5. Campaign execution & progress (R7-R9)

**Goal**: Execute campaign in background, provide progress polling, show results

**Requirements**: R7 (async execution + polling), R8 (persistence), R9 (result display)

**Dependencies**: U1 (CampaignStore), U3 (spray-backlinks multi-seed), U4 (campaign creation passes to this)

**Files**:
- Create: `webui_app/campaign_worker.py` (CampaignWorker class)
- Create: `webui_app/routes/campaign_progress.py` (progress + results page)
- Create: `webui_app/templates/campaign_progress.html` (progress/results view)
- Modify: `webui_app/__init__.py` (start CampaignWorker on app init)
- Test: `tests/test_campaign_worker.py`
- Test: `tests/test_webui_routes.py` (add polling route tests)

**Approach**:
- `CampaignWorker`:
  ```python
  class CampaignWorker:
      def __init__(self, max_workers=2):
          self.executor = ThreadPoolExecutor(max_workers=max_workers)
          self.running: dict[str, Future] = {}

      def start_campaign(self, campaign_id: str, config: dict) -> None:
          # Submit campaign as a single background job
          # The job calls spray-backlinks (or equivalent in-process) per seed
          # Updates CampaignStore after each seed completes
          future = self.executor.submit(_execute_campaign, campaign_id, config)
          self.running[campaign_id] = future

      def get_status(self, campaign_id: str) -> dict:
          # Returns CampaignStore entry + running/complete indicator
          ...

      def cancel_campaign(self, campaign_id: str) -> bool:
          # Future.cancel() for running campaigns
          ...
  ```
- Polling endpoint: `GET /api/campaign/<id>/status` returns:
  ```json
  {
      "campaign_id": "uuid",
      "status": "running",
      "progress_pct": 45.0,
      "seeds": [
          {"index": 0, "status": "success", "draft_count": 3},
          {"index": 1, "status": "processing", "draft_count": 0},
          ...
      ],
      "result_summary": null
  }
  ```
- On completion, the endpoint returns `result_summary` with per-platform breakdown
- Campaign progress page:
  - During execution: progress bar, per-seed status table, estimated time remaining
  - After completion: result summary with success/fail counts, per-platform breakdown
  - Link to draft review (if mode=draft) or back to campaign list
- Polling interval: 2 seconds (client-side setTimeout)
- CampaignWorker starts on `create_app()`, accessible via `app.config['CAMPAIGN_WORKER']`
- Concurrency: only one campaign runs at a time. If a campaign is already running, new submission is rejected with "A campaign is already in progress"
- Flask's max_content_length increased from 16KB to 1MB for multi-seed uploads

**Patterns to follow**: existing scheduler pattern in `webui_app/scheduler.py` (startup, shutdown, access via app config). Flask polling pattern: existing batch page's "请耐心等候" synchronous model is replaced; new polling uses fetch + setTimeout (no new JS dependencies)

**Test scenarios**:
- CampaignWorker.start_campaign submits job and returns immediately
- GET /api/campaign/<id>/status returns progress during execution
- Campaign status transitions: pending → running → completed (or failed)
- Per-seed status updates propagate to progress_pct correctly
- Campaign completion populates result_summary
- Concurrent campaign submission (second while first is running) returns 409
- CampaignWorker graceful shutdown on app teardown
- Progress page renders correctly during and after execution
- Flask body size limit increased (verify multipart upload of ~500KB JSONL)

**Verification**: `pytest tests/test_campaign_worker.py` green; manual: create campaign, watch progress bar update, verify result summary at end

---

### U6. Campaign draft review (R10-R13)

**Goal**: Extend existing draft review interface to support campaign-scoped drafts with approve/reject/publish flow

**Requirements**: R10-R13 (draft review dashboard, batch operations, Publish Approved)

**Dependencies**: U2 (bulk_publish_now), U5 (campaign execution creates drafts)

**Files**:
- Modify: `webui_store/drafts.py` (add `get_by_campaign_id(campaign_id)` query)
- Modify: `webui_app/routes/drafts_api.py` (add campaign_id filter to draft listing)
- Modify: `webui_app/templates/index.html` (add campaign filter to existing draft tab)
- Modify: `webui_app/static/js/draft_review.js` (extend for campaign_id context)
- Test: `tests/test_drafts_store.py` (add campaign_id query tests)
- Test: `tests/test_webui_routes.py` (add filter tests)

**Approach**:
- DraftsStore.get_by_campaign_id(campaign_id): filter drafts by campaign_id field (each draft row written during spray needs a campaign_id field — U3 ensures this)
- Existing draft tab ("草稿&历史") parameters: when navigated from campaign progress page with `?campaign_id=xxx`, show only drafts for that campaign
  - If no campaign_id, show all drafts (existing behavior unchanged)
- Each row shows: platform, title, fragment, anchor info, campaign_id badge, status
- Batch operations (existing):
  - Approve: sets draft status to "approved" (inline badge update)
  - Reject: confirmation dialog → sets status to "rejected" or removes row
  - Publish: calls bulk_publish_now (U2) → shows progress indicator → updates status inline
- "Publish Approved" button: visible when campaign_id filter is active. Publishes only drafts with status "approved" for that campaign
- Post-action state transitions:
  - Approved: badge changes to "已批准", row dimmed
  - Rejected: row removed with undo option (5-second toast)
  - Published: badge changes to "已发布" with link to article URL (if available)
  - Batch publish: shows progress "N of M completed", remaining rows update individually
- Confirmation dialogs:
  - Reject batch: "确认拒绝 N 条草稿？"
  - Publish batch: "确认发布 N 条已批准的草稿？" with draft count
  - Publish Approved: "确认发布所有已批准的草稿？" with count
- Accessibility: ARIA labels on status badges, keyboard navigation for checkbox list, focus management after batch actions, live region for action results

**Patterns to follow**: existing draft review JS and template in `webui_app/static/js/draft_review.js` and `webui_app/templates/index.html`'s draft tab section. Extend, don't replace.

**Test scenarios**:
- DraftsStore.get_by_campaign_id returns only drafts matching campaign_id
- DraftsStore.get_by_campaign_id with unknown campaign_id returns empty list
- Existing draft tab without campaign_id parameter shows all drafts (backward compat)
- Draft tab with campaign_id parameter shows only campaign drafts
- Batch approve updates multiple draft statuses simultaneously
- Batch publish calls bulk_publish_now, shows progress, updates statuses
- Reject shows confirmation dialog, on confirm removes row
- Publish Approved button only visible when campaign filter active
- Keyboard navigation works through draft list (Tab/Shift+Tab, Space to toggle)
- Action results announced to screen readers

**Verification**: `pytest tests/test_webui_routes.py` + `tests/test_drafts_store.py` green; manual: create campaign with draft mode → navigate to draft tab → approve → publish → verify flow complete

---

## System-Wide Impact

| Area | Impact |
|---|---|
| **spray-backlinks CLI** | stdin contract widens from exactly-1-row to 1..N rows. Existing single-row callers unaffected (seed_id:0 appended) |
| **queue_store** | Unchanged. CampaignWorker uses CampaignStore instead |
| **drafts_store** | Gains `get_by_campaign_id` and `bulk_publish_now`. Existing methods unchanged |
| **WebUI nav** | Gains "批量任务" tab alongside existing tabs. Draft tab gains campaign_id filter param |
| **WebUI upload size** | Flask max_content_length increased from 16KB to 1MB |
| **Existing tests** | All existing tests must remain green. Backward compatibility maintained for single-seed spray |
| **Budget files** | CampaignStore adds ~150-200 SLOC; spray_backlinks/core.py gains ~30 SLOC for multi-seed loop |

---

## Deferred Questions

| Question | Reason for Deferral |
|---|---|
| Campaign history/dashboard across campaigns | Not needed for MVP. Post-MVP when operators run 10+ campaigns |
| Retry failed seeds from campaign results | Requires UI for selective retry. Defer to follow-up |
| Per-seed platform selection (vs shared) | Assumption confirmed: shared platforms is correct for MVP. Revisit if operators request per-seed |
| Platform-level rate limiting at adapter level | Independent concern. Can be added without affecting campaign architecture |
| Combined money site cap enforcement across seeds | Rare edge case (two seeds for same money site). Defer until observed |

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| CampaignWorker thread blocks on slow platform adapter | Medium | Worker pool has 2 slots; if both blocked, new campaigns rejected with clear message |
| CampaignStore JSON file corruption from concurrent access | Low | Reader lock pattern (same as drafts_store); write atomic via tempfile + rename |
| Flask body size increase exposes DoS vector (ALLOW_NETWORK=1) | Low | Size limit is 1MB, still very restrictive for external use |
| Operators don't use campaign UI (stick to CLI) | Medium | CLI multi-seed (U3) ships first and works standalone. Campaign UI adds zero cost to CLI path |
| Existing spray-backlinks callers break from stdin contract change | Low | Verify in tests: single-row input produces identical output (seed_id field is additive) |

---

## Verification Plan

1. All existing tests green: `pytest tests/ -x -q`
2. New tests green for all 6 units
3. Manual walkthrough: CLI single seed → CLI multi seed → WebUI campaign create → campaign execute → draft review → publish
4. Backward compatibility: existing WebUI /ce:batch still works with single-row input
5. Budget gate: `python -m radon raw -s cli/spray_backlinks/core.py webui_store/campaign_store.py webui_store/drafts.py`
6. WebUI smoke test: navigate all routes, verify no 404/500
