---
date: 2026-06-05
status: completed
type: fix
topic: keepalive-net-coverage
supersedes_note: "Refines shipped keep-alive loop (plan 2026-06-04-001). Gate-first exempt: refinement of an existing shipped feature, not a new Phase machine."
---

# fix: Keep-alive net-coverage — republished sticky links resolve the gap (P2)

## Problem Frame

The keep-alive republish loop (plan 2026-06-04-001, U5–U7) creates a **new
backlink** on a sticky platform when a target's previously-live link is stripped,
then auto-rechecks (7b) to confirm the new URL went live. **But that confirming
recheck never reaches the scorecard, so the target keeps surfacing as a gap even
after a successful, confirmed republish** — the loop can never report "resolved".

Root cause (verified in code, 2026-06-05):

1. `webui_app/services/keepalive_job.py::_default_reverify` builds a recheck
   record with `live_url` + `target_url` + `platform` but **no `article_id`**, and
   the republished link is only written to `history_store` (JSON), never to
   `events.db`'s `articles` table.
2. `recheck/events_io.py::derive_per_target_status` — the keep-alive scorecard
   authority — filters `WHERE article_id IS NOT NULL AND target_url IS NOT NULL`
   and keys latest-verdict by `(canonical_target, article_id)`. The reverify
   verdict (article_id NULL) is silently dropped.
3. So `build_keepalive_view` → `plan_keepalive_gap` never sees the new live link;
   the target's only counted verdicts are the old `link_stripped`/`host_gone`, so
   `stripped > 0` keeps it in the gap set.

## Decision (operator, 2026-06-05): net-coverage, sticky-scoped

A target **exits the gap once it has a confirmed-alive link on a sticky
platform** (the republish repair channel). This is "net coverage": we stop
surfacing a target whose repair succeeded.

**Sticky-scoped, NOT blanket.** A blanket "any alive verdict ⇒ not a gap" rule
was rejected: it would also suppress a `partial-strip` (page has other live links
+ one stripped link on a non-sticky platform like telegra.ph), which is exactly
the per-link detection D1 was built for (`test_stripped_link_emits_seed`). The
gap must still surface a partial-strip until it is repaired **on a sticky
platform**. Preserving D1 is a hard requirement of this fix.

## Requirements

**Persistence (make the repair visible)**
- R1. A successful republish's confirmed-alive recheck must be counted by
  `derive_per_target_status` for that target — i.e. it must carry a real
  `article_id` and `target_url`.
- R2. The republished link must become a first-class tracked article (so the next
  full recheck cycle also sees it), not just a `history_store` JSON row.

**Gap semantics (sticky-scoped net coverage)**
- R3. `plan_keepalive_gap` must drop a target from the gap set when it has a
  latest-`alive` verdict on a **sticky** platform.
- R4. A target with dead links but alive coverage only on **non-sticky** platforms
  (partial-strip) must STILL be a gap (D1 preserved).
- R5. `probe_error` / `dofollow_lost` on the new link must not count as coverage
  (only `alive` resolves the gap); a re-stripped new link (S7 treadmill) stays a
  gap.

## Scope Boundaries

- Not touching the page-count `plan_gap` engine — only `plan_keepalive_gap`.
- Not changing the U6 dashboard banner derivation (`derive_decay_counts`).
- Not reworking the recheck→ledger liveness writeback (still deferred; the
  time-series remains the authority).
- No new platforms; sticky set stays `RUNTIME_STICKY_PLATFORMS`.

## Implementation Units

### U1 — Republished link becomes a tracked article (R1, R2)
- **Files:** `webui_app/services/keepalive_job.py` (`_run_republish` /
  `_default_persist` / `_default_reverify`); possibly a small lookup helper.
- **Approach:** after a successful publish, ensure the new `live_url` exists in
  `events.db` `articles` and obtain its `article_id`. Two candidate seams —
  decide at implementation time:
  - (a) emit a `PUBLISH_UNVERIFIED` event through the normal projection so
    `_project_reducers.add_article` creates it (most consistent with existing
    publish flow); or
  - (b) call `store.add_article(...)` directly in the reverify step, catching the
    `IntegrityError` on duplicate `live_url` and looking the id back up.
  Prefer (a) if the publish-event payload is cheap to construct here; fall back to
  (b) otherwise. Then `_default_reverify` emits the recheck with
  `article_id=<that id>` + `target_url` + `platform`.
- **Execution note:** test-first — assert the reverify verdict is now visible via
  `derive_per_target_status` before wiring.
- **Test scenarios** (`tests/test_webui_keepalive_republish.py`,
  `tests/test_recheck_events_io*.py`):
  - happy: republish→alive reverify ⇒ `derive_per_target_status[target].counts["alive"] >= 1`.
  - duplicate live_url (idempotent re-run) ⇒ no crash, reuses existing article_id.
  - failed publish ⇒ no article created, no recheck emitted.
  - probe_error reverify ⇒ article may exist but verdict is `probe_error`, not alive.
- **Verification:** a confirmed republish makes the target's per-target status
  include an `alive` verdict on the sticky platform.

### U2 — Per-target alive-platform exposure (R3, R4)
- **Files:** `src/backlink_publisher/recheck/events_io.py`
  (`derive_per_target_status`), and its consumers' type expectations.
- **Approach:** extend each per-target entry with `alive_platforms: set[str]` (or
  `live_platforms`) — the set of platforms whose **latest** verdict for that
  target is `alive`. Platform comes from the recheck event payload (`platform`).
  Keep `counts`/`total`/`last_verified` unchanged (additive field) to avoid
  breaking other readers.
- **Execution note:** characterization-first — snapshot current
  `derive_per_target_status` output shape, then add the field additively.
- **Test scenarios** (`tests/test_recheck_events_io*.py`):
  - target with latest alive on blogger ⇒ `alive_platforms == {"blogger"}`.
  - latest verdict stripped (older alive) ⇒ platform NOT in `alive_platforms`.
  - multiple articles, mixed ⇒ only latest-alive platforms included.
- **Verification:** existing `derive_per_target_status` tests still green; new
  field correct.

### U3 — Sticky-scoped net-coverage in plan_keepalive_gap (R3, R4, R5)
- **Files:** `src/backlink_publisher/gap/engine.py` (`plan_keepalive_gap`).
- **Approach:** after computing `stripped`, consult the target's
  `alive_platforms`. If `sticky_platforms ∩ alive_platforms` is non-empty, the
  target is **covered** → skip it (not a gap, no seed). Otherwise current behavior.
  `probe_error`/`dofollow_lost` never enter `alive_platforms`, so they can't
  resolve a gap (R5).
- **Execution note:** test-first.
- **Test scenarios** (`tests/test_gap_engine_stripped_aware.py`):
  - stripped old + alive on sticky (blogger) ⇒ NOT a gap (the repaired case).
  - stripped + alive only on telegraph (non-sticky) ⇒ STILL a gap, seed emitted
    (D1 partial-strip preserved — update/keep `test_stripped_link_emits_seed`
    so its alive verdicts are non-sticky to keep asserting a gap).
  - stripped + re-stripped new sticky link (no alive) ⇒ still a gap (treadmill).
  - already-live-on-all-sticky with a fresh alive ⇒ not a gap (supersedes the old
    `channel_exhausted` "still a gap with no seed" outcome — revise
    `test_already_live_on_all_sticky_is_channel_exhausted`).
- **Verification:** `plan_keepalive_gap` drops repaired targets; partial-strips on
  non-sticky platforms still surface.

### U4 — End-to-end + scorecard consistency
- **Files:** `tests/test_webui_keep_alive_status.py` (view-level).
- **Approach:** drive `build_keepalive_view` through a republish→alive cycle and
  assert the target leaves `gaps`; assert S2↔S3 stay consistent (the view and the
  job use the same `RUNTIME_STICKY_PLATFORMS`).
- **Verification:** full suite green except the documented pre-existing trunk
  baseline (~18; see memory `keepalive-loop-postship-review-findings`).

## Test Changes (explicit — these encode the decided semantics)
- `test_stripped_link_emits_seed` — keep asserting a gap, but make its alive
  verdicts non-sticky (telegraph) so net-coverage doesn't suppress it.
- `test_already_live_on_all_sticky_is_channel_exhausted` — revise: a fresh
  sticky-alive target is now dropped (not a `channel_exhausted` gap).

## Deferred to Implementation
- U1 seam choice (a vs b) — depends on how cheaply a `PUBLISH_UNVERIFIED` payload
  can be constructed in the republish worker vs a direct `add_article` + lookup.
- Whether `alive_platforms` should live on `derive_per_target_status` or a sibling
  helper (avoid bloating the hot SQL loop if it complicates the per-`(target,
  article_id)` reduction).

## Verification (whole-plan)
- New behavior covered by U1–U4 tests.
- `derive_per_target_status` backward-compatible (additive field only).
- No regression beyond the documented ~18-red trunk baseline.
- D1 partial-strip detection demonstrably preserved (R4 tests).

## Next Steps
→ `/ce:work` this plan. All units are in keep-alive-owned code
(`keepalive_job.py`, `recheck/events_io.py`, `gap/engine.py`) — agent-cold, no
collision with concurrent WebUI/docs work.
