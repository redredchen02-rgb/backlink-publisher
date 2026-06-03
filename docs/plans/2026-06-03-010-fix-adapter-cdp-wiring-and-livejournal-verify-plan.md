---
title: "fix: Wire TelegraphCdpAdapter + repair livejournal verification failure"
type: fix
status: completed
date: 2026-06-03
origin: docs/brainstorms/2026-06-03-adapter-repair-and-cdp-wiring-requirements.md
deepened: 2026-06-03
---

# fix: Wire TelegraphCdpAdapter + Repair livejournal Verification Failure

## Overview

Two independent fixes to the publishing pipeline: (1) wire `TelegraphCdpAdapter`
into the `"telegraph"` fallback chain, closing the gap left when PR #141 stalled;
(2) diagnose and repair the livejournal post-publish verification step that always
produces `published_unverified → InternalError`, even when the article publishes
successfully.

## Problem Frame

**R1 — TelegraphCdpAdapter**: The code in `instant_web.py` is complete and imported,
but the single-element `register("telegraph", TelegraphAPIAdapter, ...)` call on line 189
of `adapters/__init__.py` has never included `TelegraphCdpAdapter`. When
`TelegraphAPIAdapter` raises `DependencyError`, there is no fallback; the channel fails
silently. (see origin: docs/brainstorms/2026-06-03-adapter-repair-and-cdp-wiring-requirements.md)

**R2 — livejournal**: The 2026-05-29 livejournal publish succeeded — the article was
created on the platform. But the engine's post-publish `_do_verify()` step returned
False, appending `_unverified` to the status. The CLI layer then emitted
`InternalError: 1 payload(s) failed verification`.

Root cause confirmed during planning: `LivejournalAPIAdapter.publish()` returns
`AdapterResult(status="published", ...)` **without** a `post_publish_delay_seconds`
field. `_do_verify()` reads `result.post_publish_delay_seconds` and uses
`max_wait=30` when it is > 0 and `max_wait=10` otherwise. All other dofollow=False
adapters (devto, notion, tumblr) include this field; livejournal does not. The 10-second
window is insufficient for LiveJournal's page propagation delay.

The interstitial handling (`body_has_required_link()` → `_unwrap_interstitial()`) is
**already correct** and handles the `/away?to=...` format. That is not the bug.

The goal is referral value, not link equity — `dofollow=False` is already settled.
(see origin: docs/brainstorms/2026-06-03-adapter-repair-and-cdp-wiring-requirements.md)

## Requirements Trace

- R1. Telegraph fallback chain extended: `TelegraphCdpAdapter` appears in the dispatch
  chain after `TelegraphAPIAdapter`; when `TelegraphAPIAdapter` raises `DependencyError`
  or `available()` returns False, CDP is attempted next.
- R2. livejournal verification failure diagnosed and fixed: a successful livejournal
  publish no longer produces `InternalError`. `status` reflects the actual publish
  outcome.

## Scope Boundaries

- Not expanding to new platforms (rentry + txtfyi confirmed working 2026-06-03; no code change).
- Not changing `TelegraphAPIAdapter`'s `dofollow=True` or `dispatch_weight=0.6` (Plan 005, completed).
- Not rewriting the verification framework; livejournal fix is a minimum patch.
- Not changing livejournal's `dofollow=False` declaration.

## Context & Research

### Relevant Code and Patterns

**R1 — TelegraphCdpAdapter wiring:**
- Current register call: `adapters/__init__.py:189` —
  `register("telegraph", TelegraphAPIAdapter, dofollow=True, **TELEGRAPH_MANIFEST)`
- TelegraphCdpAdapter import (already present): `adapters/__init__.py:79–81` —
  `TelegraphCdpAdapter, # noqa: F401  kept for test import, not yet wired`
- Registry dispatch contract: `publishing/_registry_dispatch.py:78–127`
  - `DependencyError` (base class, not `AuthExpiredError`) → fall-through to next adapter
  - `available()` returns False → `continue` silently (no error stored, no exception)
  - `ExternalServiceError` → propagates; next adapter is never tried
  - `AuthExpiredError` (DependencyError subclass) → propagates immediately, no fall-through
- Reference fallback chain: Medium 3-adapter chain at `adapters/__init__.py:181–188`
- Existing telegraph tests (no CDP coverage yet):
  `tests/test_adapter_telegraph_api.py`,
  `tests/test_adapter_telegraph_api_self_heal.py`,
  `tests/test_telegraph_live_verify.py`

**R2 — livejournal verification:**
- livejournal publish call: `livejournal_api.py:304` — calls `attach_link_verification()`
  (fire-and-forget, never fails, only records metadata in `_provider_meta`)
- The failing verification is NOT `attach_link_verification`. It is the engine gate:
  `publish_backlinks/_engine.py:309–313` → `_do_verify()` in `_publish_helpers.py:265–286`
  → `verify_published()` checks the live page for required links
- InternalError emit: `_publish_helpers.py:542–598` — status ending in `_unverified`
  triggers `emit_envelope_and_exit("InternalError", 5, ...)`
- livejournal interstitial: all external links are wrapped in
  `https://www.livejournal.com/away?to=<url-encoded-target>`. The interstitial-aware
  comparison lives in `link_attr_verifier.py:431–462` (`body_has_required_link()`).
- Check whether `_do_verify()` / `verify_published()` invokes the interstitial-aware
  path or falls back to a naive URL substring match.

### Institutional Learnings

- **Fallback chain testing**: Must mock ALL adapter layers (1 to N-1), not just the
  first and last. `@patch` decorators are applied bottom-up; parameter order in the test
  function signature is reversed relative to decorator order. Add a comment above the
  mock stack describing the chain order.
  (docs/solutions/test-failures/ci-test-isolation-failures-medium-brave-sleep-timeout-2026-05-13.md)

- **`published_unverified` emit paths**: Both the fresh-publish path (`base.py::to_publish_output`)
  and the resume path (`_resume.py::item_to_publish_output`) must carry the field.
  Use a shared carry-helper rather than duplicating copy logic.
  (docs/solutions/integration-issues/dofollow-canary-verdict-dropped-at-publish-output-seam-2026-05-25.md)

- **Exception handling policy**: Browser/CDP exceptions must not be silently swallowed.
  Narrow try blocks, `from exc` re-raise, no bare `except Exception: pass`.
  (docs/solutions/correctness/adapter-silent-exceptions-resolution.md)

- **livejournal is confirmed dofollow=False**: Goal of any livejournal work is referral
  value and entity signal, not link equity.
  (docs/solutions/dofollow-platform-shortlist.md)

## Key Technical Decisions

- **`TelegraphCdpAdapter` appended after (not before) `TelegraphAPIAdapter`**: The API
  adapter requires no Chrome binary. CDP requires Chrome. Binary-free path is always
  attempted first; CDP is the fallback. Placement mirrors the Medium chain
  ordering principle (lowest-dependency first).

- **`available()` is the primary CDP skip gate**: When Chrome is absent, `available()`
  returns False and the dispatch loop silently continues past `TelegraphCdpAdapter`.
  The `DependencyError` path (raised inside `publish()` when Chrome is missing) is a
  secondary guard for the case where `available()` incorrectly returns True but Chrome
  setup fails at publish time.

- **livejournal fix is `post_publish_delay_seconds` in `AdapterResult`**: Root cause is
  confirmed during planning. Adding this field gives `_do_verify()` `max_wait=30`
  instead of 10, matching the behavior of devto/notion/tumblr. This is a one-field
  addition to `livejournal_api.py`'s return statement. The interstitial handling is
  already correct and does not require changes.

- **livejournal `InternalError` should not surface for platform-expected behavior**: The
  fix (longer verification window) addresses the root cause. If verification still fails
  after the fix, the fallback is a per-platform `post_publish_delay_seconds` increase,
  not a framework-level bypass.

## Open Questions

### Resolved During Planning

- **"`attach_link_verification` = `_do_verify()`?"**: No. `attach_link_verification`
  (fire-and-forget) never fails. `_do_verify()` is the engine gate that marks
  `_unverified`. The livejournal bug is in `_do_verify()`.
- **"Is the interstitial the bug?"**: No. `verify_published()` → `_link_in_body()`
  → `body_has_required_link()` → `_unwrap_interstitial()` already handles
  `/away?to=...` correctly. Not the root cause.
- **"What is the livejournal root cause?"**: Missing `post_publish_delay_seconds` in
  `livejournal_api.py`'s `AdapterResult`. This caps `max_wait` at 10 instead of 30.
  Fix: add `post_publish_delay_seconds` (same as devto/notion/tumblr).
- **"Does the resume path need a separate fix?"**: No. `_resume.py:416` calls the same
  `_do_verify()`. One change to `AdapterResult` fixes both paths.
- **"Does TelegraphCdpAdapter need new `register()` kwargs?"**: No. Inherits channel
  metadata from the existing `register()` call.
- **"Does `TelegraphCdpAdapter.available()` already handle Chrome-absent?"**: Yes.
  `_ChromeSession.available()` returns False when Chrome binary absent. No extra guard.

### Deferred to Implementation

- **`_do_verify()` called for `dofollow=False` platforms**: Confirmed — `_engine.py:309–313`
  calls `_do_verify()` unconditionally after every publish result, no `dofollow` gate.
  The fix is valid and will take effect.
- **Env var name**: Use `LIVEJOURNAL_PUBLISH_DELAY_S` (follows `<PLATFORM>_PUBLISH_DELAY_S`
  convention from devto/notion/tumblr). Define constant `_LIVEJOURNAL_PUBLISH_DELAY_ENV`
  and helper `_post_publish_delay_s()` matching the other adapter patterns.
- **Exact `_DEFAULT_POST_PUBLISH_DELAY_S` value**: Read the devto or notion adapter at
  implementation time and use the same integer default.
- **Whether `max_wait=30` is sufficient**: If verification still fails intermittently,
  increase the livejournal-specific delay; root cause is now measurable.

## Implementation Units

- [ ] **Unit 1: Wire TelegraphCdpAdapter into telegraph chain**

**Goal:** Append `TelegraphCdpAdapter` to the `register("telegraph", ...)` call so it
acts as fallback when `TelegraphAPIAdapter` raises `DependencyError`. Update the import
comment.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `src/backlink_publisher/publishing/adapters/__init__.py`
- Test (new): `tests/test_adapter_telegraph_cdp_chain.py`

**Approach:**
- Change `adapters/__init__.py:189` from:
  `register("telegraph", TelegraphAPIAdapter, dofollow=True, **TELEGRAPH_MANIFEST)`
  to:
  `register("telegraph", TelegraphAPIAdapter, TelegraphCdpAdapter, dofollow=True, **TELEGRAPH_MANIFEST)`
- Update import comment on line 80: remove `kept for test import, not yet wired`
- Verify `TelegraphCdpAdapter` raises `DependencyError` (not `ExternalServiceError`) in
  its Chrome-absent code path — if not, the dispatch contract requires it. Review
  `instant_web.py` before coding.
- Do NOT add a `register()` call for `TelegraphCdpAdapter` separately — it joins the
  existing single-channel `register()`.

**Patterns to follow:**
- Medium fallback chain: `adapters/__init__.py:181–188`
- `MediumBraveAdapter.available()` — how `available()` is the primary skip gate
- Medium fallback chain tests — how to mock every layer and annotate the chain order

**Test scenarios:**
- Happy path: `registered_adapters("telegraph")` (or equivalent registry inspection)
  returns a sequence containing `TelegraphAPIAdapter` before `TelegraphCdpAdapter`
- Skip via `available()`: when `TelegraphCdpAdapter.available()` is patched to return
  False, a mock `TelegraphAPIAdapter` success → dispatch returns the API result without
  calling CDP
- Fall-through via `DependencyError`: when `TelegraphAPIAdapter.publish()` raises
  `DependencyError`, dispatch tries `TelegraphCdpAdapter`; mocked CDP publish returns
  success → outer result is the CDP result
- `ExternalServiceError` does not fall through: when `TelegraphAPIAdapter.publish()`
  raises `ExternalServiceError`, it propagates immediately; assert `TelegraphCdpAdapter`
  was never called (verify via mock call count)
- `AuthExpiredError` does not fall through: `AuthExpiredError` (DependencyError subclass)
  propagates without trying CDP — verify same way
- All-fail: both adapters raise `DependencyError` in sequence → dispatch re-raises the
  last `DependencyError`

**Verification:**
- `pytest tests/test_adapter_telegraph_cdp_chain.py -v` — all green
- `pytest tests/test_adapter_telegraph_api.py tests/test_adapter_telegraph_api_self_heal.py -v` — still green (no regression)
- `tests/test_r9_extension_readiness.py` — still green (single `register()` call invariant preserved)

---

- [ ] **Unit 2: Fix livejournal post-publish verification timeout**

**Goal:** Add `post_publish_delay_seconds` to `LivejournalAPIAdapter`'s `AdapterResult`
so `_do_verify()` uses `max_wait=30` instead of 10, giving the page time to propagate
before link verification. Root cause confirmed during planning: this field is missing in
livejournal while all other adapters (devto, notion, tumblr) include it.

**Requirements:** R2

**Dependencies:** None (independent of Unit 1)

**Files:**
- Modify: `src/backlink_publisher/publishing/adapters/livejournal_api.py`
- Test: `tests/test_adapter_livejournal_api.py` (existing — add new scenario)

**Approach:**
- Find the `return AdapterResult(status="published", ...)` statement in `livejournal_api.py`
  (around line 295–305)
- Add `post_publish_delay_seconds=_post_publish_delay_s()` to the return — define the
  helper function following the exact same pattern as `devto_api.py` or `notion_api.py`
  (env-var override + `_DEFAULT_POST_PUBLISH_DELAY_S` fallback)
- Confirm: `_do_verify()` in `_publish_helpers.py:265–286` reads
  `result.post_publish_delay_seconds` and sets `max_wait=30` when it is > 0

This is intentionally a minimal, single-file change. Do NOT change:
- `_do_verify()` itself (no per-platform branching needed)
- `link_attr_verifier.py` (interstitial handling is already correct)
- `_engine.py` or `_resume.py` (both call the same `_do_verify()` and will benefit
  from the AdapterResult change without modification)

**Patterns to follow:**
- `devto_api.py` — `_post_publish_delay_s()` + `_DEFAULT_POST_PUBLISH_DELAY_S` + env var
- `notion_api.py` — same helper pattern
- Existing `livejournal_api.py:295–305` return statement — add one field

**Test scenarios:**
- Happy path: `livejournal_api.publish()` returns an `AdapterResult` where
  `post_publish_delay_seconds > 0`; assert the value equals the default or the env-var
  override
- Delay env-var: set `LIVEJOURNAL_PUBLISH_DELAY_S=15` → `post_publish_delay_seconds == 15`
- `_do_verify()` integration: mock livejournal's `AdapterResult` with the new field
  → assert `verify_published()` is called with `max_wait=30` (not 10)
- Draft mode unaffected: livejournal publish in `mode="draft"` returns
  `status="drafted"` without `_do_verify()` being called (already tested; no regression)
- Regression: `tests/test_adapter_livejournal_api.py:test_publish_happy_returns_published_url`
  still green (adding a field does not break existing assertions unless they check
  field absence)

**Verification:**
- `pytest tests/test_adapter_livejournal_api.py -v` — all green including new scenario
- A fresh livejournal publish no longer produces `InternalError` (verify in dry-run
  against a mock or staging environment where the verification window is observable)

---

## System-Wide Impact

- **Interaction graph**: Unit 1 modifies registration in `adapters/__init__.py` (import
  time). Unit 2 modifies `livejournal_api.py` only — the `AdapterResult` change
  propagates automatically to `_do_verify()` in both the engine path and the resume
  path (both call the same function). No middleware, webhooks, or background jobs affected.
- **Error propagation**: Unit 1 — `ExternalServiceError` from `TelegraphAPIAdapter`
  propagates unchanged. `DependencyError` now falls through to CDP before being
  re-raised. Unit 2 — fix is scoped to livejournal's verification path; error handling
  for other platforms is unchanged.
- **State lifecycle risks**: Unit 1 — no state; registration is immutable at import time.
  Unit 2 — existing `published_unverified` records in `publish-history.json` are not
  backfilled (forward-only fix).
- **API surface parity**: Unit 1 — callers of `registered_adapters("telegraph")`
  (including `test_r9_extension_readiness.py`) now see two adapters. Verify no existing
  test asserts a single-element list. Unit 2 — no external API change.
- **Unchanged invariants**: `TelegraphAPIAdapter` remains the primary telegram adapter;
  its `dofollow=True` and `dispatch_weight=0.6` are unchanged. livejournal stays
  `dofollow=False`. No other adapter registration changes.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `@patch` mock order in fallback chain tests wrong (bottom-up decorator reversal) | Follow Medium adapter tests; add comment above mock stack documenting chain order |
| Chrome installed but CDP handshake fails → `ExternalServiceError` (not fall-through) | Read `instant_web.py:_wait_for_cdp()` to confirm; add test: "Chrome found, CDP timeout → ExternalServiceError propagates without fall-through" |
| `__init__.py` SLOC ceiling (268/290, 22 lines remaining) | Run `python -m radon raw -s adapters/__init__.py` before and after Unit 1; bump `monolith_budget.toml` in same PR with ≥80-char rationale if ceiling hit |
| `max_wait=30` still insufficient for livejournal after fix | If failures continue, increase the livejournal-specific `_DEFAULT_POST_PUBLISH_DELAY_S` — root cause is now measurable |
| Resume path needs separate fix | Not needed: `_resume.py:416` calls the same `_do_verify()`; `AdapterResult` change propagates automatically to both paths |

## Sources & References

- **Origin document**: [docs/brainstorms/2026-06-03-adapter-repair-and-cdp-wiring-requirements.md](docs/brainstorms/2026-06-03-adapter-repair-and-cdp-wiring-requirements.md)
- Registry dispatch: `src/backlink_publisher/publishing/_registry_dispatch.py:78–127`
- Adapter chain registration: `src/backlink_publisher/publishing/adapters/__init__.py:181–189`
- TelegraphCdpAdapter: `src/backlink_publisher/publishing/adapters/instant_web.py`
- livejournal adapter: `src/backlink_publisher/publishing/adapters/livejournal_api.py:304`
- Interstitial verification: `src/backlink_publisher/publishing/adapters/link_attr_verifier.py:431–462`
- Verification gate: `src/backlink_publisher/cli/_publish_helpers.py:265–286, 542–598`
- Engine verification: `src/backlink_publisher/cli/publish_backlinks/_engine.py:309–313`
- Institutional learnings:
  - docs/solutions/test-failures/ci-test-isolation-failures-medium-brave-sleep-timeout-2026-05-13.md
  - docs/solutions/integration-issues/dofollow-canary-verdict-dropped-at-publish-output-seam-2026-05-25.md
  - docs/solutions/correctness/adapter-silent-exceptions-resolution.md
  - docs/solutions/dofollow-platform-shortlist.md
