---
title: "fix: residual test-suite failures on Windows (8 failed / 1 error, stable snapshot)"
type: fix
status: active
date: 2026-07-13
claims: {}
# claims paths deferred until this branch merges — plan-check validates
# claimed paths against origin/main; work happens on
# fix/windows-test-suite-triage (isolated worktree
# bp-fix-windows-test-suite/, base commit 7cf782db on local main, which is
# 46 commits ahead of un-pushed origin/main).
---

# Fix: Residual Test-Suite Failures on Windows (2026-07-13-002)

## Overview

This plan supersedes `docs/plans/2026-07-13-001-fix-windows-test-suite-failures-plan.md`
(an untracked file left in the shared `backlink-publisher/` checkout — safe
to delete once this plan is reviewed). That earlier plan was built from a
full local `pytest tests/` run showing 122 failed / 11 errored, but was
diagnosed while another concurrent session was actively merging ~15+
branches into this shared, non-worktree-isolated directory (a
previously-documented hazard for this workspace, now its fifth confirmed
incident — see `docs/solutions/` / project memory). Two independent
doc-review agents (adversarial, feasibility) caught the staleness during
review: they re-ran the same tests against a newer `main` HEAD and found
most of the original 122/11 already fixed by a directly-overlapping prior
plan, `docs/plans/2026-07-07-005-fix-windows-dev-loop-triage-plan.md`
(merged 6 days earlier via `fix/windows-dev-loop-triage`), which this
document never cited.

To get a stable target, this work now happens in an isolated git worktree
(`bp-fix-windows-test-suite/`, branch `fix/windows-test-suite-triage`)
pinned at local `main`'s HEAD at the time of creation, commit `7cf782db`
("fix(gates): bring merged WIP features through the governance gates") —
**46 commits ahead of `origin/main`**, so this snapshot includes work not
yet pushed. A full suite run against this pinned commit, repeated and
cross-checked with isolated single/small-group re-runs to separate genuine
bugs from load-induced flakes, produced a small, confirmed, reproducible
set: **8 failed, 1 error, 13162 passed, 83 skipped**. This plan targets
exactly those.

## Problem Frame

Unlike the superseded plan, every failure here has been reproduced at least
twice against a fixed commit with no interleaving external changes — via a
full-suite run, an isolated 4-test re-run, and (for the persona test) two
further isolated re-runs that surfaced an order-dependency worth flagging
rather than hiding. The failures split into four independent root causes:
two stale test-mock targets left over from unrelated refactors (SSRF-guard
migration, per-host session pooling), one `os.environ` test-isolation
anti-pattern with an existing documented fix pattern, one genuine
Windows-clock-resolution timestamp-collision bug in a shared snapshot/
archive-naming helper, and one still-open Windows file-locking race in the
reliability-circuit's cross-process trip path.

## Requirements Trace

- R1. Each of the 8 failed tests and 1 errored test, reproduced against
  commit `7cf782db`, is root-caused and fixed.
- R2. The fix for the timestamp-collision bug (Unit 3) addresses its shared
  root cause once, not per call site, since it affects at least two
  independent subsystems (config snapshot rotation, secrets orphan-archive
  naming) via one shared helper family.
- R3. Any failure that could not be confirmed as a deterministic bug (the
  persona concurrent-first-use test, confirmed order-dependent rather than
  reliably reproducible) is triaged, not silently fixed by guesswork.
- R4. This plan is reconciled against `docs/plans/2026-07-07-005-fix-windows-dev-loop-triage-plan.md`
  before any unit starts, so no unit re-diagnoses work that plan already
  completed.

## Scope Boundaries

- This plan only addresses the 8 failed / 1 error set confirmed against
  commit `7cf782db` in the isolated worktree. It is not a general Windows
  compatibility audit.
- The Windows POSIX-permission-semantics gap (`os.chmod` not restricting
  NTFS access) that the superseded plan spent significant scope on is
  **not** revisited here — `docs/plans/2026-07-07-005-...`'s shared
  `tests/_mode_assertions.py::assert_file_mode()` helper already handles
  it, and none of the 8 current failures are permission-bit assertions.
- Continuing to work in the shared `backlink-publisher/` directory is out
  of scope for this plan's execution — implementation happens in the
  `bp-fix-windows-test-suite/` worktree on branch
  `fix/windows-test-suite-triage`, merged back when done.

### Deferred to Separate Tasks

- Deleting the superseded, untracked
  `backlink-publisher/docs/plans/2026-07-13-001-fix-windows-test-suite-failures-plan.md`
  file: left for the user or a future session to confirm before removing,
  since it sits in the actively-shared directory.

## Context & Research

### Relevant Code and Patterns

- `src/backlink_publisher/publishing/adapters/http_form_post.py::_session_for_host` —
  the per-host `requests.Session` pool (commit `2269b14e`, "perf: per-host
  requests.Session pool in http_form_post (C3)") that Unit 2's stale mocks
  don't account for.
- `webui_app/routes/llm.py::_safe_post_json` +
  `src/backlink_publisher/llm/http_guard.py` — the SSRF-guarded LLM POST
  path Unit 1 fixes the test mock for.
- `src/backlink_publisher/persistence/safe_write.py::rotate_snapshots` and
  `src/backlink_publisher/_util/secrets.py`'s orphan-archive stamp (both
  independently generate a `datetime.now(UTC).strftime(...%f...)`
  microsecond timestamp for uniqueness) — Unit 3's shared root cause.
- `src/backlink_publisher/publishing/reliability/circuit.py::trip` /
  `_acquire_lock` and `src/backlink_publisher/_compat/fcntl.py` — Unit 4's
  target; the Windows `flock` shim was already patched once by
  `docs/plans/2026-07-07-005-...`, but the cross-process `trip()` scenario
  still deadlocks.
- `tests/test_locked_health_store.py::test_concurrent_writes_no_lost_update` —
  Unit 5's target.

### Institutional Learnings

- `docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md` —
  the exact anti-pattern Unit 5 fixes, previously documented.
- `docs/plans/2026-07-07-005-fix-windows-dev-loop-triage-plan.md` — landed
  the Windows `flock`-shim offset fix, `_canonicalise_for_sha`
  `.as_posix()` fix, `conftest.py` `USERPROFILE` sandbox redirect, cp950
  `encoding="utf-8"` fixes, and the shared `assert_file_mode()` permission
  helper. None of that work is repeated here; this plan's Unit 4 builds on
  top of its `flock` fix rather than redoing it, since the current failure
  mode (a 60-second lock-timeout, not a `PermissionError`) is a different
  symptom than what that plan fixed.
- Project memory `workspace-shared-directory-no-worktree-isolation` — this
  is the fifth confirmed incident of concurrent, uncoordinated sessions
  operating in this shared directory; mitigation applied here (isolated
  worktree) matches that memory's guidance.

## Key Technical Decisions

- **Work happens in an isolated worktree, not the shared `backlink-publisher/`
  checkout:** confirmed necessary in practice — `git rev-parse HEAD`
  changed twice during this planning session alone while reading files in
  the shared directory.
- **Unit 3's timestamp-collision fix targets the shared helper, not each
  call site individually:** `rotate_snapshots` and `secrets.py`'s
  `_archive_orphan_token`-equivalent both independently reimplement the
  same "UTC microsecond timestamp for uniqueness" pattern and both broke
  the same way; a single disambiguation strategy (e.g. an appended
  monotonic/random suffix) applied to both, rather than two bespoke fixes,
  avoids the same bug recurring a third time in a future third call site.
- **The persona concurrent-first-use test is triaged, not blindly "fixed":**
  it passed in two separate isolated re-runs (solo, and paired with
  `test_config_safety_net.py`) and only failed once, embedded deep in the
  full 13,171-test suite — consistent with order-dependent pollution from
  an unidentified other test, not a deterministic bug in `persona.py`
  itself. Guessing a fix without isolating the actual polluting test risks
  masking a real (but different) test-isolation bug elsewhere.

## Open Questions

### Resolved During Planning

- "Is the repo state this plan is built from stable?" → No, twice
  confirmed unstable in the shared checkout; resolved by moving to an
  isolated worktree pinned at commit `7cf782db`.
- "Should Unit 3 fix each timestamp call site separately or the shared
  pattern once?" → Once, via the shared root cause, per Key Technical
  Decisions above.

### Deferred to Implementation

- Which other test pollutes `test_events_persona.py::test_concurrent_first_use_falls_through_to_read`
  when run as part of the full suite — needs a bisection (e.g. `pytest
  --lf` after a full run, or narrowing via `-k`/file-range splitting)
  during Unit 6, not resolved in this plan.
- Whether Unit 4's cross-process lock-timeout in `reliability/circuit.py`
  is a genuinely new regression or a latent bug the prior triage plan's
  fix exposed by changing timing — the standalone repro in Unit 4's
  Execution note should clarify which.

## Implementation Units

- [x] **Unit 1: Fix stale SSRF-redirect-guard test mock target**

**Goal:** Make `test_safe_post_json_rejects_redirect` actually exercise the
live SSRF-guard code path instead of silently attempting a real network
call (currently blocked by `pytest_socket`, confirmed via the traceback
showing `socket.getaddrinfo('api.openai.com', ...)` being reached).

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `tests/test_webui_unit3_security.py`
  (`TestLlmSsrfRedirectGuard::test_safe_post_json_rejects_redirect`)

**Approach:**
- The test monkeypatches `webui_app.routes.llm.requests.post`, but
  `_safe_post_json` in that module has been migrated to call through a
  guarded session/`http_guard` path instead of raw `requests.post` (same
  migration that already left a stale `ALLOWLIST` entry — since fixed
  upstream, confirmed absent from the current 8-failure list). Read
  `webui_app/routes/llm.py::_safe_post_json` to find the actual current
  call site and update the monkeypatch target to intercept it.
- Preserve the test's intent: a 307 response with a `Location` header must
  raise `ValueError` matching `"redirect_not_allowed"`.

**Test scenarios:**
- Error path: a 307 redirect response from the (correctly-mocked) call
  site raises `ValueError("redirect_not_allowed")`, with the mock's
  `calls` list confirming it was actually invoked (not bypassed).

**Verification:**
- `tests/test_webui_unit3_security.py` passes with no `pytest_socket`
  warning/error anywhere in its output.

- [x] **Unit 2: Fix stale mocked-session bypass in `test_catalog_e2e.py`**

**Goal:** Make all three `TestConfigDrivenAdapterE2E` tests exercise their
mocked HTTP response instead of falling through to a real network call.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `tests/test_catalog_e2e.py`
  (`test_happy_path_redirect_permalink`, `test_happy_path_draft_mode`,
  `test_json_path_permalink`)

**Approach:**
- Root cause (confirmed): all three tests do
  `patch("backlink_publisher.publishing.adapters.http_form_post.requests.post", ...)`,
  but `submit_form()` in that module calls
  `_session_for_host(url).post(...)` — a bound method on a cached
  `requests.Session` instance, not the module-level `requests.post`
  function. Patching the module-level function never intercepts the
  session-bound call, so the real socket path runs and `pytest_socket`
  blocks it.
- Fix: patch `_session_for_host` itself (e.g. to return a
  `MagicMock`/fake session whose `.post()` returns the test's prepared
  mock response), or patch `requests.Session.post` at the class level
  instead of the module-level function — pick whichever keeps the tests'
  existing `mock_resp`/`return_value` shape with the smallest diff.

**Test scenarios:**
- Happy path: all three existing test bodies pass unchanged in assertion
  content once the mock target is corrected.
- Regression: confirm no other test in this file (or `_neutralize_form_post_ssrf`,
  the shared autouse fixture at the top of the class) relies on the old
  mock shape in a way this change would break.

**Verification:**
- `tests/test_catalog_e2e.py` passes with no `pytest_socket` warning.

- [x] **Unit 3: Fix Windows timestamp-collision bug in snapshot/archive naming**

**Goal:** Stop `rotate_snapshots()` and the secrets orphan-archive writer
from silently colliding (and clobbering each other) when two rotations
happen close together on Windows, where `datetime.now(UTC)` microsecond
resolution is coarser in practice than the `%f` format suggests.

**Requirements:** R1, R2

**Dependencies:** None

**Files:**
- Modify: `src/backlink_publisher/persistence/safe_write.py`
  (`rotate_snapshots`)
- Modify: `src/backlink_publisher/_util/secrets.py` (orphan-archive stamp,
  around line 247)
- Test: `tests/test_config_safety_net.py`
  (`test_save_config_rotates_snapshots_at_cap`), `tests/test_secrets.py`
  (`test_two_rotations_produce_two_distinct_archives`,
  `test_orphan_archive_suffix_is_microsecond_utc` — format assertion
  updated for the new disambiguator suffix), `tests/test_image_gen_token_rotation.py`
  (`test_write_frw_token_orphan_archive_has_microseconds` — same format
  update; discovered during Unit 6 verification, not in the original scan)

**Approach:**
- Root cause (confirmed twice, with two different collision counts across
  two runs — 1-of-2 archives, and separately 14-of-20 snapshots): both
  `rotate_snapshots()` and the secrets-archive writer generate their
  filename uniqueness suffix purely from
  `datetime.now(UTC).strftime("...%f...")`. On this Windows machine the
  underlying system clock's actual update granularity is coarser than one
  microsecond, so rapid successive calls (a tight loop in
  `test_save_config_rotates_snapshots_at_cap`, or two back-to-back
  rotations in `test_two_rotations_produce_two_distinct_archives`) can
  observe the identical timestamp string, producing the identical target
  filename — the second write silently overwrites the first.
- Fix direction: append a disambiguating suffix that does not depend on
  wall-clock resolution — e.g. a short random hex suffix (`os.urandom`),
  a monotonic counter, or `time.perf_counter_ns()` — to both call sites.
  Since both already independently reimplement the same pattern, consider
  factoring the timestamp-plus-disambiguator generation into one shared
  helper (in `persistence/safe_write.py` or `_util/`) that both import,
  per Key Technical Decisions above.

**Test scenarios:**
- Happy path: `test_save_config_rotates_snapshots_at_cap`'s loop of 25
  rapid saves produces exactly `_CONFIG_HISTORY_MAX` (20) distinct
  snapshot files, no fewer.
- Happy path: `test_two_rotations_produce_two_distinct_archives` produces
  exactly 2 distinct archive files, not 1.
- Edge case: two calls issued back-to-back in the same test process (no
  `sleep`) never collide, regardless of how fast the clock actually
  advances on the host.

**Verification:**
- `tests/test_config_safety_net.py` and `tests/test_secrets.py` pass.

- [~] **Unit 4: Investigate and fix residual cross-process lock timeout in reliability circuit — PARTIAL, see Outcome below**

**Outcome (2026-07-13):** Investigated but not fully root-caused; downgraded
from "fix" to "mitigation + documented open issue." The leading hypothesis
(msvcrt lock/unlock targeting different byte offsets due to a moved file
position) was directly disproven by a standalone repro — position stayed
at 0 across lock/unlock in this environment. A raw-primitive stress test
(400 lock/unlock cycles across 2 real processes, 1 ms poll) showed **zero**
failures, isolating the issue to something specific to the full `trip()`
call path (state read/write/log) under real subprocess contention, not the
locking primitive itself. Added jittered backoff to
`_acquire_lock` (`_LOCK_POLL_INTERVAL * random.uniform(0.5, 1.5)`) as a
defensible, low-risk improvement against synchronized-retry contention, but
measured failure rate before/after was statistically unchanged (~30% across
~10 runs each). CPU load was low (6%) during failing runs, weakening the
"other concurrent session is starving this one for CPU" theory. This
remains a genuine, intermittent, unresolved issue — needs dedicated
follow-up debugging (e.g. Windows-native lock tracing, or instrumenting
`trip()`'s internals with per-step timestamps) beyond what was practical to
complete here.

**Goal:** Stop `test_crossproc_trip_distinct_platforms_both_survive` from
timing out — one of the two real child processes waits the full 60 seconds
for `publish-circuit-state` lock and then raises `ExternalServiceError`,
meaning the other process's lock is never actually released even after it
finishes and exits.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `src/backlink_publisher/publishing/reliability/circuit.py`
  (`trip`, `_acquire_lock`) and/or `src/backlink_publisher/_compat/fcntl.py`
  (pending root-cause confirmation)
- Test: `tests/test_reliability_circuit_crossproc.py`
  (`test_crossproc_trip_distinct_platforms_both_survive`)

**Execution note:** Investigate-then-fix. This reproduced deterministically
in three separate runs (full suite, isolated 4-test batch, solo re-run),
each taking ~65 seconds (the 60s stale-lock threshold plus overhead) — so
it is not a timing flake, but the prior triage plan
(`docs/plans/2026-07-07-005-...`) already fixed the `flock` shim's
lock/unlock offset mismatch, and this failure's symptom (a clean timeout,
not a `PermissionError`) is different from what that plan targeted.
Instrument `_acquire_lock`/`trip` to log lock-acquire and lock-release
timestamps with the PID, then re-run the two-child-process test to see
directly whether the first (`medium`) process's lock survives past its own
process exit, before changing production code.

**Approach:**
- Starting hypothesis: the first child process's `trip()` call logs
  `circuit_tripped` successfully (confirmed in the captured stderr) and
  then exits — if its lock is still held from the OS's perspective after
  that exit (e.g. the file descriptor wasn't actually closed, or
  `msvcrt.locking(LK_UNLCK)` silently no-ops under some condition the
  fixed shim doesn't yet cover), the second process would see exactly this
  60-second hang-then-timeout pattern.
- Fix at the specific point the instrumentation identifies, rather than
  broadening beyond what's demonstrated.

**Test scenarios:**
- Happy path: two real OS processes tripping two different platforms
  concurrently through `trip()` both complete successfully and both
  platforms' tripped state survives in the final on-disk state
  (`test_crossproc_trip_distinct_platforms_both_survive` passes without
  timing out).
- Regression: `tests/test_reliability_circuit.py` and
  `tests/test_reliability_circuit_crossproc.py`'s other test(s) still pass
  — don't regress the already-fixed single-process/offset-mismatch
  behavior from the prior triage plan.

**Verification:**
- `tests/test_reliability_circuit_crossproc.py` passes in full, completing
  well under the 60s stale-lock threshold.

- [x] **Unit 5: Fix `os.environ` test-isolation leak in `test_locked_health_store.py`**

**Goal:** Stop `test_concurrent_writes_no_lost_update` from leaving
`BACKLINK_PUBLISHER_CONFIG_DIR` mutated in `os.environ` after teardown.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `tests/test_locked_health_store.py`

**Approach:**
- Root cause (confirmed, line 128): `os.environ["BACKLINK_PUBLISHER_CONFIG_DIR"] = str(tmp_path)`
  is a direct assignment, not `monkeypatch.setenv(...)`, so it is never
  auto-reverted and trips the `_env_isolation_guard` autouse fixture. This
  is the exact anti-pattern already documented in
  `docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md`.
- Fix: replace the direct assignment with `monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))`
  (the test already needs a `monkeypatch` fixture parameter, or can add
  one).

**Test scenarios:**
- Happy path: `test_concurrent_writes_no_lost_update` passes and leaves
  `os.environ` unmutated after teardown.

**Verification:**
- `tests/test_locked_health_store.py` passes with no isolation-guard
  failure.

- [~] **Unit 6: Full-suite re-run, order-dependency triage, and close-out — PARTIAL, see Outcome below**

**Outcome (2026-07-13):** Ran the full suite three more times after Units
1, 2, 3, 5 landed. Units 1/2/3/5's target tests pass consistently and
cleanly across all runs — confirmed solid. Two intermittent failures
remain, neither part of this plan's original scope and neither fixed:
`test_reliability_circuit_crossproc.py::test_crossproc_trip_distinct_platforms_both_survive`
(Unit 4, documented above) and a newly-surfaced flake,
`test_geo_run.py::TestProbeManyBudget::test_wall_clock_budget_stops_batch`
(appeared in 1 of 3 final runs; its own docstring already acknowledges
wall-clock timing fragility — "We can't easily control time.monotonic(),
so use a tiny budget"). The persona order-dependency bisection
(`test_events_persona.py::test_concurrent_first_use_falls_through_to_read`)
was not attempted — that test passed cleanly in every final run and did
not recur, so it was deprioritized given the two still-open, higher-signal
flakes above.

**Goal:** Confirm Units 1-5 collectively fix what they claim, and either
resolve or clearly document the one remaining order-dependent test.

**Requirements:** R3, R4

**Dependencies:** Units 1-5

**Files:**
- None (verification-only; may produce a small follow-up fix if the
  polluting test is found and trivial to fix, otherwise a documented note)

**Approach:**
- Re-run the full suite in the isolated worktree
  (`PYTHONHASHSEED=0 ../backlink-publisher/.venv/Scripts/python.exe -m pytest tests/ -q --no-header`)
  and confirm 0 failures / 0 errors from this plan's scope.
- Bisect `test_events_persona.py::test_concurrent_first_use_falls_through_to_read`'s
  order dependency: run the full suite with `-x --lf` after an initial
  failing run, or binary-search file ranges (e.g.
  `pytest tests/test_a*.py ... tests/test_events_persona.py`) to find the
  specific test that leaves state (most likely a stale `persona._load_salt`
  cache entry, a leaked config-dir env var, or a leaked monkeypatch on
  `persona.os.open`) affecting this test. If found and the fix is a small,
  contained test-isolation cleanup (e.g. an explicit
  `persona._load_salt.cache_clear()` in a fixture teardown), fix it as
  part of this unit. If the culprit is unclear after a reasonable bisection
  effort, document the finding (which combination reproduces it) rather
  than guessing a fix.

**Test scenarios:**
- Test expectation: none — verification/triage unit, not new behavior.

**Verification:**
- Full-suite run against the worktree shows this plan's 8-failed/1-error
  set fully resolved, with the order-dependent persona test either fixed
  or documented with its reproducing condition.

## System-Wide Impact

- **Interaction graph:** Unit 3's shared timestamp-disambiguation fix
  touches both the config-snapshot and secrets-archive subsystems — verify
  neither has an existing test asserting the *exact* filename format
  (only distinctness/count), which would need updating alongside the fix.
- **Unchanged invariants:** POSIX (Linux/macOS) behavior is unchanged by
  every unit — all five reproduced failures are Windows-specific in
  mechanism (session-pool/mock mismatch and env-leak are OS-agnostic bugs
  that merely happen to be caught here, but their fixes don't change POSIX
  behavior either).

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Unit 4's lock-timeout root cause isn't confirmed by instrumentation, leading to a guessed fix | Execution note requires a logged repro before any production-code change |
| Unit 6's order-dependency bisection for the persona test consumes disproportionate time relative to its severity (a single, non-deterministic test) | Cap effort; document-not-fix is an acceptable outcome per this unit's Approach |
| The other concurrent session merges again while this worktree's work is in progress | Isolated worktree is immune to the shared checkout's branch/HEAD churn; only merging back at the end re-exposes this, so keep this branch short-lived |

## Sources & References

- Full suite run (unstable, superseded): shared `backlink-publisher/`
  checkout, 2026-07-13, 122 failed / 11 errored — see superseded plan
  `2026-07-13-001-fix-windows-test-suite-failures-plan.md`.
- Full suite run (stable, authoritative): isolated worktree
  `bp-fix-windows-test-suite/`, branch `fix/windows-test-suite-triage`,
  commit `7cf782db`, 2026-07-13 — 8 failed, 1 error, 13162 passed, 83
  skipped, 468.67s. Reconfirmed via isolated re-runs of the 4 uncertain
  failures (65.30s, all 4 reproduced) and two further isolated re-runs of
  the persona test alone (both passed, establishing the order-dependency).
- `docs/plans/2026-07-07-005-fix-windows-dev-loop-triage-plan.md` (prior,
  directly-overlapping work — reconciled against, not duplicated)
- `docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md`
  (Unit 5)
- Project memory: `workspace-shared-directory-no-worktree-isolation`
  (fifth confirmed incident, recorded during this plan's own drafting)
