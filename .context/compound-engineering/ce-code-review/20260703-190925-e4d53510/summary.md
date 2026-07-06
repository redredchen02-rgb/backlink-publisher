# Code review summary — B1 (pr-queue LITE error message)

Branch: fix/pr-queue-lite-error-message-2 (base f835820e, review head 698ac012)
Mode: autofix. 10 reviewers: correctness, testing, maintainability, project-standards,
agent-native, learnings-researcher, security, reliability, kieran-typescript, julik-frontend-races.

## Applied fix
correctness + reliability + kieran-typescript independently converged on the same issue:
the initial diff wrapped the new `/app-config` read and `fetchPrQueue()` in a single
try/catch, so a transient `/app-config` failure would block an otherwise-healthy
`/api/pr-queue` fetch in full edition. Fixed: the LITE check now fails open (best-effort;
any /app-config error is treated as non-LITE and falls through to the real fetch).
Added 2 tests (fail-open on /app-config rejection; missing lite_edition field treated as
non-LITE). 6/6 PrQueuePage tests pass, 246/246 full suite, typecheck clean.

## Clean reviewers (no findings)
project-standards, agent-native, security, testing (testing had only advisory gaps, no defects).

## Learnings-researcher note
Top-cited doc (webui-config-request-cache-governance-2026-06-03.md) was verified and found
to be about backend Python load_config() memoization, not frontend Vue Query caching —
discounted as a mismatched citation, not applied.

## Pre-existing findings (verified against base f835820e, not introduced by this diff — not fixed, recorded in docs/audits/2026-07-03-webui-feature-error-backlog.md as B3/B4)
- B3: fetchPrQueue()/updatePrStatus() (frontend/src/api/prQueue.ts) have no timeout/AbortController,
  unlike client.ts's getJson/sendJson. reliability P2, confidence 0.75, pre_existing:true.
- B4: load() has no request-generation guard against overlapping invocations
  (markStatus()'s internal reload vs. manual refresh) — last-resolving response wins,
  not last-started. julik-frontend-races confidence 0.85; reliability P3/advisory,
  confidence 0.6. Confirmed pre-existing via `git show f835820e:...PrQueuePage.vue`.

## Advisory, not actioned (reviewer's own recommendation: not now)
- maintainability: extract a shared AppConfig type/useAppConfig() composable once a 3rd
  consumer appears (currently only TopBar.vue + PrQueuePage.vue).
