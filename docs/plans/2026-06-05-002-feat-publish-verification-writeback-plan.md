---
title: "feat: Publish verification writeback and uncertain-platform dofollow resolution"
type: feat
status: active
date: 2026-06-05
---

# feat: Publish verification writeback and uncertain-platform dofollow resolution

## Overview

Three concrete gaps limit the equity ledger's `live_dofollow` count and leave
published links stuck in `unverified` or `uncertain` classification forever:

1. **Keepalive recheck has no ledger writeback**: `_run_recheck()` calls
   `emit_recheck()` which appends `link.rechecked` events to events.db — but
   never updates `articles.verified_at`. The ledger reads liveness from
   `articles.verified_at` via `history_query`, so keepalive probe results have
   zero effect on the equity ledger (only on the plan-gap overlay).

2. **`published_unverified` records are locked out of the recheck pool**:
   `_confirmed_universe()` only selects `publish.confirmed` events. Any article
   whose post-publish verify failed (`publish.unverified`) stays in
   `liveness="unverified"` permanently, regardless of later re-probe results.

3. **Sixteen registered platforms carry `dofollow="uncertain"`**: `_classify()`
   returns `"uncertain"` class for these, so `live_dofollow += 1` never fires
   even when `probe_liveness()` already confirmed the anchor has no nofollow
   attribute. The probe result is silently discarded.

This plan closes all three gaps in a sequenced, read-safe way.

## Problem Frame

The equity ledger's `live_dofollow` count is the canonical scorecard metric
operators see. Each gap below causes systematic under-counting:

| Gap | Root cause | Effect on ledger |
|-----|-----------|-----------------|
| Keepalive no writeback | `_run_recheck` never calls `UPDATE articles SET verified_at` | All keepalive probes show zero benefit in ledger |
| Unverified locked out | `_confirmed_universe` filters `kind = publish.confirmed` only | ~50% of published links permanently `liveness="unverified"` |
| Uncertain class ignored | `_classify` returns `"uncertain"` → excluded from `live_dofollow` | 16-platform pool contributes 0 to live_dofollow |

## Requirements Trace

- R1. Keepalive recheck `alive` verdicts must update `articles.verified_at`
  → ledger `_link_liveness` returns `"live"` for probed-alive links
- R2. `publish.unverified` records must enter the recheck candidate pool with
  a retry window appropriate for eventual confirmation
- R3. For `uncertain` platforms, `probe_liveness` must emit a `confirmed_dofollow`
  signal when the anchor probe shows no nofollow attribute
- R4. `build_ledger` must consume `confirmed_dofollow` signals to count
  verified-dofollow uncertain-platform links in `live_dofollow`
- R5. No double-counting: a link confirmed as dofollow via probe AND live must
  appear exactly once in `live_dofollow`

## Scope Boundaries

- No new event kinds added to `events/kinds.py` — `link.rechecked` payload is
  extended (additive, floor is `frozenset({"verdict"})`)
- No changes to `overlay.py` or `cli/recheck_overlay.py` (plan-gap layer)
- No automatic registry mutation (`dofollow="uncertain"` → `True`) — per-article
  confirmation only; registry update remains a manual governance step
- Does not touch `webui_app/services/recheck.py` (manual one-shot recheck) —
  its `history_store.update_item()` write path already works correctly

## Context & Research

### Relevant Code and Patterns

- `src/backlink_publisher/recheck/events_io.py:emit_recheck()` — the existing
  append path for `link.rechecked` events; `write_verified_at()` will be added here
- `webui_store/history.py:_update_item_events_db()` — reference pattern for
  `UPDATE articles SET verified_at = ? WHERE article_id = ?` (uses `store.connect()`)
- `src/backlink_publisher/recheck/selection.py:_confirmed_universe()` — mirror
  this to create `_unverified_universe()`; same shape, different `kind` constant
- `src/backlink_publisher/recheck/probe.py:probe_liveness()` lines 174–184:
  the `target_is_nofollow` decision tree — extend the `False` branch for uncertain
- `src/backlink_publisher/ledger/aggregate.py:_classify()` and `build_ledger()`:
  add `confirmed_dofollow_urls` set parameter to `_classify()`; pre-compute in
  `build_ledger()` before the main loop via a single store query
- `src/backlink_publisher/recheck/overlay.py` — reference read pattern for
  `link.rechecked` payload queries (recency-keyed set, `ts_utc` + `events.id`
  tiebreaker); `_load_confirmed_dofollow_urls` in `aggregate.py` mirrors this
  pattern but is placed in the ledger layer, not in `overlay.py` (which is
  out of scope per Scope Boundaries)

### Institutional Learnings

- `docs/solutions/logic-errors/projector-silent-drop-status-vocabulary-drift.md`:
  projector silent-drop lesson — no `else` branch in classifiers; unknown verdicts
  must be quarantined, not silently treated as "live". The `confirmed_dofollow`
  promotion in `_classify()` must follow the same fail-closed pattern.
- `docs/solutions/integration-issues/dofollow-canary-verdict-dropped-at-publish-output-seam.md`:
  `nofollow_detected` page-level scan is noisy (nav/footer links); `inspect_target_anchor`
  returns the per-anchor `target_is_nofollow` — that is the correct signal.
- Memory `invariant-hardening-plan-corrects-c0`: recheck must never emit a second
  `publish.confirmed` event (double-counts in health metrics). Write to
  `articles.verified_at` directly; do not append a new `publish.confirmed`.
- Memory `reliability-policy-circuit-facts`: circuit trip threshold is
  `BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD`, not `CONSECUTIVE_ERRORS`.

## Key Technical Decisions

- **Write `articles.verified_at` from `events_io.py` (not from `keepalive_job.py`)**:
  Co-locating the writeback with `emit_recheck()` keeps the contract tight —
  both the event append and the projection update share the same result payload,
  same `alive` verdict check, and the same `article_id` pointer. The keepalive
  job continues to call a single function and stays ignorant of the SQL layer.

- **`_unverified_universe` uses `min_retry_days=7` (vs confirmed pool's `1`)**:
  Unverified articles need a generous re-probe interval to avoid hammering
  platforms where the initial verify failed due to transient conditions. 7 days
  balances responsiveness with anti-bot caution. The confirmed pool's 14-day
  cycle and 1-day retry floor are left unchanged.

- **`confirmed_dofollow` as an additive `link.rechecked` payload field**:
  Extending the existing payload avoids a new event kind, preserves the `KINDS`
  set gate (R9 CI), and keeps the floor `frozenset({"verdict"})` unchanged.
  Absent `confirmed_dofollow` in older events means `False` (fail-closed).

- **Pre-compute `confirmed_dofollow_urls` as a set before `build_ledger()` loop**:
  One extra store query up-front (same pattern as `overlay.py`) rather than
  per-link queries inside the loop. Set membership check is O(1). The set is
  keyed on canonical `live_url` (same canonicalization as the link bucket key).

- **`_classify()` receives `confirmed_dofollow_urls` as a parameter (not a global)**:
  Keeps `_classify()` pure/testable and avoids coupling aggregate.py to store
  access inside the hot path. `build_ledger()` passes an empty set when no store
  is available (test isolation).

## Open Questions

### Resolved During Planning

- **"Can we emit a second `publish.confirmed` to fix the unverified case?"** No.
  Would double-count in `health_metrics.py` per-adapter projector (invariant
  confirmed by memory `invariant-hardening-plan-corrects-c0`).

- **"Should the unverified pool use the same cursor as the confirmed pool?"** No.
  The confirmed pool cursor tracks `last_definitive_at` from `link.rechecked`
  events. Unverified articles have no `link.rechecked` cursor yet, so they sort
  to the front automatically on the first probe pass.

- **"Should uncertain-platform links use the overlay (plan-gap layer) or the
  ledger directly for promotion?"** Ledger directly (`aggregate.py`). The overlay
  is a throwaway bridge for the plan-gap CLI; the equity ledger has its own build
  path. Putting promotion in `aggregate.py` avoids duplicating the logic.

### Deferred to Implementation

- **`publish.unverified` events and `article_id=NULL`**: `publish_writer.map_history_entry()`
  writes `publish.unverified` events via `write_event()` with `article_id=None`
  (default). Only the projector path (`_project_reducers.py:263`) sets `article_id`
  when emitting `publish.unverified`. This means a portion of `publish.unverified`
  events in events.db may have `article_id=NULL`. The `_unverified_universe` query
  with `article_id IS NOT NULL` will silently exclude these. Before shipping U2,
  run `SELECT COUNT(*) FROM events WHERE kind='publish.unverified' AND article_id IS NULL`
  to assess the production impact. If significant, the query will need a fallback
  join on `live_url` (like overlay.py's approach). Deferring to implementation
  to audit which path dominates in the live database.

- **`_classify` call-site grep**: Before coding U3, grep for `_classify` in
  `tests/` to confirm all test calls use the positional-only form `_classify(platform)`.
  The new keyword-only signature `_classify(platform, *, ...)` is backward-safe
  for positional callers but may break tests that use `_classify(platform, frozenset())` positionally.

## High-Level Technical Design

> *Directional guidance for review, not implementation specification.*

```
┌──────────────────────────────────────────────────────────────────────┐
│ BEFORE (gaps)                                                        │
│                                                                      │
│  keepalive._run_recheck()                                            │
│    → emit_recheck()  ──────────── writes link.rechecked event only  │
│                        ×          articles.verified_at: NEVER written│
│                                                                      │
│  recheck/selection._confirmed_universe()                             │
│    → only kind = publish.confirmed                                   │
│                        ×          publish.unverified: excluded       │
│                                                                      │
│  aggregate._classify(platform)                                       │
│    → "uncertain" for 16 platforms → live_dofollow += 0              │
│                        ×          probe confirmed dofollow: discarded│
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│ AFTER (U1 + U2 + U3 sequenced)                                       │
│                                                                      │
│  keepalive._run_recheck()                                            │
│    → emit_recheck() + write_verified_at()  ──► articles.verified_at │
│      (U1 — additive call, same results list)                         │
│                                                                      │
│  recheck/selection                                                   │
│    → select_candidates()         (publish.confirmed pool, unchanged) │
│    → select_unverified_candidates() (publish.unverified pool, U2)   │
│      both pools → _run_recheck → write_verified_at                  │
│                                                                      │
│  aggregate.build_ledger()                                            │
│    → pre-load confirmed_dofollow_urls (one query, U3)                │
│    → _classify(platform, live_url, confirmed_dofollow_urls)          │
│      "uncertain" + in set → "dofollow" → live_dofollow += 1         │
└──────────────────────────────────────────────────────────────────────┘
```

## Implementation Units

```
U1 ──► U2

U3  (independent — no dependency on U1 or U2)
```
Each unit is independently shippable; U2 depends on U1's `write_verified_at`
write path, and U3 is fully independent of both.

---

- [ ] **Unit 1: Keepalive recheck → `articles.verified_at` writeback**

**Goal:** Ensure `alive` verdicts from the keepalive recheck loop update
`articles.verified_at`, making equity ledger liveness reflect probe results.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `src/backlink_publisher/recheck/events_io.py`
- Modify: `webui_app/services/keepalive_job.py`
- Test: `tests/test_recheck_verified_at_writeback.py`

**Approach:**
- Add `write_verified_at(store, results)` to `events_io.py`:
  - Takes the same `results` list as `emit_recheck()`
  - For each result where `result["verdict"] == ALIVE` and `result.get("article_id")` is not None:
    - `UPDATE articles SET verified_at = <now_iso>, verify_error = NULL WHERE article_id = ?`
  - One connection/transaction for all updates (follow `_update_item_events_db` pattern)
  - Skip if `article_id` is missing (stdin-sourced rechecks have NULL article_id)
- In `_run_recheck()` in `keepalive_job.py`, call `write_verified_at(store, [result])`
  after `emit_recheck(store, [result])` — same try/except wrapper (a write failure
  must not abort the worker or lose progress)
- `write_verified_at` uses `datetime.now().isoformat(timespec="seconds")` (naive
  local time, no tz suffix) — same convention as `webui_app/services/recheck.py`
  line 115 (`"verified_at": datetime.now().isoformat(timespec="seconds")`).
  Use `int(article_id)` for the WHERE binding (not `str(aid)` as in the
  `_update_item_events_db` reference — `article_id` flows as `int` from the
  candidate dict, matching the `INTEGER PRIMARY KEY` column type)

**Patterns to follow:**
- `webui_store/history.py:_update_item_events_db()` — `UPDATE articles SET` pattern
- `events_io.py:emit_recheck()` — transaction scope and error handling
- `keepalive_job.py:_run_recheck()` — try/except wrapper around per-result writes

**Test scenarios:**
- Happy path: candidate with `verdict=alive` and `article_id=5` → after call,
  `SELECT verified_at FROM articles WHERE article_id=5` returns a non-NULL timestamp
- Verdict not alive (`link_stripped`): `verified_at` NOT updated (still NULL)
- Missing article_id (`article_id=None`): no error, no write, function returns 0
- Multiple results in one call: only `alive` ones get `verified_at` updated
- Integration: `_run_recheck()` with an injected `emit_recheck` stub
  → after probe returns `alive`, `build_ledger()` returns `liveness="live"` for that link

**Verification:**
- `emit_recheck()` and `write_verified_at()` are called sequentially in `_run_recheck`
- A link that was `liveness="unverified"` before a keepalive pass is
  `liveness="live"` after `_run_recheck()` completes with an `alive` verdict

---

- [ ] **Unit 2: Add `published_unverified` records to the recheck candidate pool**

**Goal:** Articles whose post-publish verify failed should be re-probed
periodically so they can graduate to `liveness="live"` once the platform
makes the page accessible.

**Requirements:** R2

**Dependencies:** Unit 1 (write_verified_at must exist to benefit from the new pool)

**Files:**
- Modify: `src/backlink_publisher/recheck/selection.py`
- Modify: `webui_app/services/keepalive_job.py`
- Test: `tests/test_recheck_selection_unverified.py`

**Approach:**
- Add `_unverified_universe(store, *, since, host, run_id)` to `selection.py`:
  - Same shape as `_confirmed_universe()` but queries `kind = PUBLISH_UNVERIFIED`
  - Include only records where `live_url` is non-null in the payload
- Add `select_unverified_candidates(store, *, now, cap=20, min_retry_days=7, ...)`
  to `selection.py`:
  - Eligibility: `last_attempt_at` is None or older than `min_retry_days=7`
    (the `days` / `last_definitive_at` gate from `select_candidates` is omitted
    here — for unverified candidates `last_definitive_at` is always `None` on
    first pass and remains `None` after `probe_error` verdicts, making `days`
    a dead parameter; only `min_retry_days` is load-bearing)
  - Smaller default cap (20) to avoid overwhelming the confirmed pool budget
  - `min_retry_days=7` — weekly retry; anti-bot caution for platforms that
    may still be rendering the page
- In `KeepaliveJob._run_recheck()`:
  - When `candidates is None` (normal keepalive run): load confirmed pool via
    `_default_candidates(store)`, then append unverified pool via
    `_default_unverified_candidates(store)`; set `job.total = len(combined)`
  - When `candidates` is explicitly injected (tests): unchanged — no unverified pool added
  - Both pools iterate through the same per-result loop:
    `probe_fn(cand)` → `emit_recheck` → `write_verified_at` → `job.checked += 1`
- Add `_default_unverified_candidates(store)` helper that calls
  `select_unverified_candidates(store, now=datetime.now())`

**Patterns to follow:**
- `selection.py:_confirmed_universe()` / `select_candidates()` — mirror exactly
- `keepalive_job.py:_run_recheck()` — same per-result loop, same error handling

**Test scenarios:**
- Happy path: `publish.unverified` event in store with non-null `live_url` →
  `select_unverified_candidates()` returns that candidate
- Already probed within 7 days (`min_retry_days`): candidate is NOT returned
- `publish.confirmed` event in store: NOT selected by `_unverified_universe`
- Cap respected: 25 unverified candidates → only 20 returned (default cap)
- Integration: `_run_recheck()` processes unverified pool → `alive` verdict →
  `articles.verified_at` updated → `build_ledger()` returns `liveness="live"`
- Error path: probe returns `link_stripped` for unverified → no `verified_at`
  update; candidate reappears in pool after 7 days

**Verification:**
- `select_unverified_candidates()` exists and passes a symmetry test against
  `select_candidates()` (same fields in returned dicts)
- A `published_unverified` article that receives an `alive` probe appears
  as `liveness="live"` in the equity ledger within the next keepalive pass

---

- [ ] **Unit 3: Emit + consume `confirmed_dofollow` for uncertain-platform probes**

**Goal:** When `probe_liveness()` confirms that an `uncertain` platform's anchor
has no nofollow attribute, that fact should (a) be recorded in the
`link.rechecked` payload, and (b) cause `build_ledger()` to count the link
as effective dofollow in `live_dofollow`.

**Requirements:** R3, R4, R5

**Dependencies:** None (independent of U1/U2)

**Files:**
- Modify: `src/backlink_publisher/recheck/probe.py`
- Modify: `src/backlink_publisher/recheck/events_io.py`
- Modify: `src/backlink_publisher/ledger/aggregate.py`
- Test: `tests/test_uncertain_platform_dofollow_promotion.py`

**Approach:**

*probe.py — emit the signal:*
- In `probe_liveness()`, in the `target_is_nofollow` decision tree (lines ~174–184):
  - **Gate: `confirmed_dofollow` is only reachable when `target_anchor_found=True`** —
    when `target_url` is empty (line ~148 `if not target: return ALIVE`) or the anchor
    is not found (line ~152 `if not res.get("target_anchor_found"): ...`), execution
    returns before reaching this block. Do NOT add `confirmed_dofollow` to those
    early-return paths. `res.get("target_is_nofollow")` defaults to `False` in
    `link_attr_verifier`, so checking `target_is_nofollow is False` alone would
    silently false-positive confirm dofollow on liveness-only probes.
  - When `dofollow_status(platform) == "uncertain"` AND
    `res.get("target_anchor_found")` AND NOT `res.get("target_is_nofollow")`:
    add `out["confirmed_dofollow"] = True` at line ~183 (before final `return out`)
  - When `dofollow_status(platform) == "uncertain"` AND `res.get("target_is_nofollow")`:
    add `out["confirmed_nofollow"] = True` in the `expected_nofollow=True` block
    at line ~181 — both flags are set together (`expected_nofollow=True` is NOT
    removed; `confirmed_nofollow=True` is additive)
  - When platform is `None` or `dofollow_status` is `True/False`: unchanged

*events_io.py — carry the signal through:*
- In `emit_recheck()`, add `"confirmed_dofollow": bool(r.get("confirmed_dofollow", False))`
  and `"confirmed_nofollow": bool(r.get("confirmed_nofollow", False))` to the
  payload dict (additive; floor is `frozenset({"verdict"})` — no floor change)

*aggregate.py — consume the signal:*
- Add `store = store or EventStore()` at the **top of `build_ledger()`** (before
  calling `build_target_buckets`). This ensures the `store` reference in
  `build_ledger`'s local scope is always a real `EventStore`. Currently,
  `build_target_buckets(store=None)` resolves `store` internally but does NOT
  reassign the `store` variable in the caller's scope.
- Add `_load_confirmed_dofollow_urls(store)` — a module-level function that:
  - Queries `events` where `kind = "link.rechecked"` (full-table scan, same
    pattern as `overlay.py`; one query per `build_ledger()` call)
  - For each row: parse `payload_json`, apply `canonicalize_url()` (or `_canon()`)
    to `payload["live_url"]` before keying — the `live_url` in the payload is raw
    (not canonicalized at write time); `LinkRecord.live_url` in the aggregate loop
    IS canonical (`sources.py:_canon()`), so the set key must match
  - Returns `frozenset[str]` of canonical `live_url`s where the **latest**
    `link.rechecked` event has `confirmed_dofollow=True` (recency by `ts_utc`,
    `events.id` as tiebreaker — same pattern as `overlay.py`)
  - Returns empty frozenset when `store` is `None` (test isolation; also now
    unreachable in normal operation since `build_ledger` resolves `store` first)
- Modify `_classify(platform, *, confirmed_dofollow_urls=frozenset(), live_url=None)`:
  - When `status == "uncertain"`: check `live_url and live_url in confirmed_dofollow_urls`
    → if True, return `("dofollow", None)` — counts in `live_dofollow`
    → if False, return `("uncertain", None)` — unchanged
  - Fail-closed: absent `confirmed_dofollow_urls` (default frozenset) → no promotion
- Modify `build_ledger()`:
  - After adding `store = store or EventStore()` at top, call
    `confirmed_dofollow_urls = _load_confirmed_dofollow_urls(store)`
  - In the per-link `_classify()` call, pass `confirmed_dofollow_urls=confirmed_dofollow_urls,
    live_url=link.live_url`

**Patterns to follow:**
- `recheck/overlay.py` — `link.rechecked` payload read pattern, recency-keyed set
- `aggregate.py:_classify()` — extend signature with keyword-only parameters
  (Python signature change is non-breaking when caller passes positional arg)
- `events_io.py:emit_recheck()` — additive payload field (boolean, default False)

**Test scenarios:**
- Happy path: `uncertain` platform, `target_is_nofollow=False` → probe returns
  `confirmed_dofollow=True` in result dict; emitted `link.rechecked` payload
  carries `confirmed_dofollow=True`
- Nofollow case: `uncertain` platform, `target_is_nofollow=True` → result carries
  BOTH `expected_nofollow=True` (existing field, unchanged) AND `confirmed_nofollow=True`
  (new additive field); `confirmed_dofollow` absent or False; NO `DOFOLLOW_LOST`
  verdict (only `dofollow=True` platforms trigger that)
- Known dofollow platform (`dofollow=True`): probe logic unchanged, no `confirmed_dofollow` emitted
- `_load_confirmed_dofollow_urls`: multiple `link.rechecked` events for same `live_url`
  with different `confirmed_dofollow` values → latest (by `ts_utc`) wins
- `_classify` with promotion: `platform="substack"`, `live_url` in
  `confirmed_dofollow_urls` → returns `("dofollow", None)`
- `_classify` without promotion: `platform="substack"`, `live_url` NOT in set →
  returns `("uncertain", None)` (unchanged)
- Integration `build_ledger()`: seed `link.rechecked` with `confirmed_dofollow=True`
  for an uncertain platform → `LedgerRow.live_dofollow` increases by 1,
  `live_dofollow_platforms` includes that platform
- R5 no double-count: a link where `liveness=live` AND `_classify` returns
  `"dofollow"` (via uncertain-platform promotion) contributes exactly 1 to
  `live_dofollow` — the same `if status == "live": if cls == "dofollow": live_dofollow += 1`
  path used for all platforms; verified by seeding a single promoted-uncertain
  link and asserting `row.live_dofollow == 1`

**Verification:**
- `build_ledger()` with a seeded `link.rechecked confirmed_dofollow=True` event
  produces `live_dofollow > 0` for an uncertain-platform target
- `build_ledger()` with no `link.rechecked` events produces same result as before
  (no regression on confirmed/nofollow platforms)

## System-Wide Impact

- **Interaction graph**: `_run_recheck` in `keepalive_job.py` now has a second
  side-effect (beyond `emit_recheck`): `write_verified_at`. This is the only
  caller change. `select_candidates` callers (CLI `recheck-backlinks`) are
  unaffected — `write_verified_at` lives in `events_io.py` and is opt-in.
- **Error propagation**: `write_verified_at` shares the same swallow-and-continue
  try/except as `emit_recheck` in the keepalive worker — a DB write failure does
  not abort the recheck pass.
- **State lifecycle risks**: `articles.verified_at` is overwritten on each `alive`
  verdict — this is the correct behavior (each probe is the freshest signal).
  `articles.verify_error` is cleared to NULL on `alive` (mirrors `recheck_one`).
- **API surface parity**: `cli/recheck_backlinks.py` calls `emit_recheck()` but
  not `write_verified_at()` — by design; the CLI pipe's liveness is tracked via
  `link.rechecked` events and the overlay, not via `articles.verified_at`. No
  change needed there.
- **Integration coverage**: The liveness judgment chain
  `keepalive probe → articles.verified_at → ledger._link_liveness()` is the
  primary integration to verify; it crosses the events_io ↔ SQL ↔ ledger layer
  boundary and will not be proven by unit tests alone.
- **Unchanged invariants**: `LINK_RECHECKED` floor stays `frozenset({"verdict"})`;
  the `KINDS` set is unchanged; `overlay.py` is untouched; `dofollow_status()`
  registry values are read-only.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `write_verified_at` fails silently and keeps liveness stale | Same try/except wrapper as `emit_recheck`; failure logged; next keepalive pass retries |
| Unverified pool bloats the keepalive run duration | Default cap of 20; confirmed pool processed first (higher signal candidates first) |
| `_load_confirmed_dofollow_urls` is slow on large events.db | Single SQL scan with no subquery; same read pattern as overlay.py, which already runs per equity-ledger page load |
| Latest-event recency logic in `_load_confirmed_dofollow_urls` misidentifies winner on same-`ts_utc` tie | Use `events.id` as tiebreaker (same fix applied in overlay.py per its own docstring) |
| `confirmed_dofollow=True` for a link that later gains nofollow | The latest `link.rechecked` event wins; if next recheck shows nofollow, `confirmed_dofollow=False` displaces the old True entry |
| `build_ledger` CC currently ~22 (grade D); adding `_load_confirmed_dofollow_urls` call may push past CC=30 backstop | Measure `build_ledger` CC after U3 changes; add a named-set entry in `complexity_budget.toml` in the same PR if CC ≥ 25 |
| `publish.unverified` events with `article_id=NULL` silently excluded from U2 pool | Run SQL audit pre-merge; if > 10% of unverified events have NULL article_id, extend `_unverified_universe` with a live_url fallback join |

## Sources & References

- Related code: `src/backlink_publisher/recheck/events_io.py`, `selection.py`,
  `probe.py`, `ledger/aggregate.py`, `webui_app/services/keepalive_job.py`
- Related pattern: `src/backlink_publisher/recheck/overlay.py`
- Related solution: `docs/solutions/logic-errors/projector-silent-drop-status-vocabulary-drift.md`
- Related solution: `docs/solutions/integration-issues/dofollow-canary-verdict-dropped-at-publish-output-seam.md`
- Memory: `invariant-hardening-plan-corrects-c0`, `reliability-policy-circuit-facts`
