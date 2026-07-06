# Code Review: B3/B4/B5 fixes (PR-queue timeout, request-generation guard, dismiss-recheck)

**Scope:** `4e188a17..71e19232` (branch `fix/pr-queue-lite-error-message-2`)
**Files:** `frontend/src/api/prQueue.ts`, `frontend/src/api/prQueue.spec.ts`, `frontend/src/pages/PrQueue/PrQueuePage.vue`, `frontend/src/pages/PrQueue/PrQueuePage.spec.ts`, `webui_app/static/js/index.js`, `tests/test_webui_feedback_states.py` (doc-only backlog update out of scope)
**Reviewers:** correctness, testing, maintainability, project-standards, agent-native, learnings (always-on) + reliability, adversarial, kieran-typescript, julik-frontend-races (10 — diff touches timeouts, async races, TypeScript/Vue, and legacy vanilla-JS)

## Findings and resolution

| # | Finding | Reviewer(s) | Severity | Resolution |
|---|---------|-------------|----------|------------|
| 1 | `updatePrStatus` chains two independent 15s timeouts (CSRF fetch then status POST) = ~30s worst case, double the fix's own stated 15s intent. Confirmed via `spa.py`/`index.html` that this SPA never has a CSRF `<meta>` tag, so this is the *normal* code path every click takes, not a rare fallback. | reliability, adversarial, julik-frontend-races (independent 3-way convergence) | P2 (confidence 0.85) | **Deferred to backlog** — needs a design call (cache token at module scope vs. shared deadline vs. accept). Recorded as B6 in `docs/audits/2026-07-03-webui-feature-error-backlog.md`, mirroring how B3/B4/B5 themselves originated from B1/B2's reviews. |
| 2 | `markStatus`'s catch block silently discards `updatePrStatus` failures — its own comment ("Error is surfaced by load()") is inaccurate. Pre-existing, but B3's new timeout gives it a new, deterministic trigger. | correctness (formal finding) + reliability, adversarial, julik (corroborating) | P2 (confidence 0.85) | **Deferred to backlog** — needs a UX call on how to surface the failure. Recorded as B7. |
| 3 | The 15s AbortController timeout's real timer/abort wiring was never exercised by a test (mocks jumped straight to a synthetic rejection) | testing (formal) + reliability, kieran-typescript, adversarial, julik (all independently flagged) | P2 | **Fixed** — added a `vi.useFakeTimers()` test that advances past the real 15s window. |
| 4 | `_csrf()`'s network-fallback branch (no `<meta>` tag present) had zero test coverage despite the diff touching that exact call | testing (formal) + kieran-typescript, adversarial, julik (corroborating) | P2 | **Fixed** — added `updatePrStatus` tests with an empty `document.head`, covering both success and rejection of the fallback fetch. |
| 5 | B4's test only exercised the `/app-config` generation checkpoint, not the `fetchPrQueue`-in-flight checkpoint the bug is actually about | testing (formal) + reliability, adversarial, julik (corroborating) | P2 | **Fixed** — added a test with two independently-controlled deferred promises that both reach `fetchPrQueue()` before either resolves. |
| 6 | B5's regression test asserted a whole-file literal string count rather than the guard's position inside the `.then()` callback | testing (formal) + julik (corroborating) | P3 | **Fixed** — anchored the assertion to the callback body specifically. |
| 7 | Timeout-wrapper logic (`_fetchWithTimeout`/`_TIMEOUT_MS`) duplicated verbatim from `client.ts` rather than extracted to a shared module | maintainability | P3 (confidence 0.64) | Not actioned — real but low-stakes drift risk; noted for a future consolidation pass, not blocking. |
| 8 | `loadGeneration` hand-rolls a race-guard that `useQuery` (already used in sibling pages) gives for free | kieran-typescript | P3 (confidence 0.62) | Not actioned — architectural suggestion, explicitly out of scope for this targeted bugfix. |
| 9 | No `onUnmounted` cancellation for in-flight `load()` | julik-frontend-races | P3 (confidence 0.62) | Not actioned — bounded to 15s already by B3's timeout; minor. |

## Cross-references confirmed clean

- **project-standards**: zero findings — frontend anti-rot rules (no `innerHTML`, CSRF read-per-call), legacy-JS testing convention, and naming conventions all respected.
- **agent-native**: no gaps — these are pure internal reliability fixes with zero endpoint-contract changes; CLI parity (`pr-opportunities` console script) for the PR-queue data is untouched. Flagged one forward-looking observation: the new timeout collapses into `classifyError.ts`'s generic "unknown" bucket, indistinguishable from any other failure — not a blocker since that file is untouched by this diff.
- **adversarial**: tried hard to break B4's generation-guard (same-row races, 3+-way overlapping calls, `updating` Set clearing) and B5's dismiss-recheck — both hold up structurally, no exploitable interleaving found.
- **learnings**: no `docs/solutions/` entry covers fetch-timeout, request-generation-guard, or dismiss-race patterns. Found that `webui_app/static/js/monitor_hub.js` already solved the identical "out-of-order response" race via a different mechanism (AbortController identity vs. B4's counter) — worth naming as a known pattern rather than reinventing vocabulary if a third instance appears.

## Verification after fixes

- `npx vitest run` (full frontend suite): 255/255 before fixes; re-verified green after the 3 new frontend tests landed.
- `PYTHONPATH=src pytest tests/test_webui_feedback_states.py`: 15/22 pass (7 pre-existing, unrelated Windows `cp950`-codec subprocess failures, confirmed present on the pre-B2 baseline too — not a regression).

**Verdict: Ready with fixes — all P2 testing-gap findings (#3-6) fixed; the two substantive P2 behavioral findings (#1-2) recorded as new backlog entries (B6, B7) rather than scope-creeping this PR, consistent with how B3/B4/B5 themselves originated on this same branch; three P3 findings (#7-9) are discretionary and non-blocking.**
