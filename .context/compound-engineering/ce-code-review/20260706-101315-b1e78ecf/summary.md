# Code Review: B2 fix (health banner never-published vs. degraded)

**Scope:** `fd9349cf..a341bfa9` (branch `fix/pr-queue-lite-error-message-2`)
**Files:** `webui_app/static/js/index.js`, `webui_app/static/css/index.css` (doc changes out of scope)
**Reviewers:** correctness, testing, maintainability, project-standards, agent-native, learnings, julik-frontend-races (7 — no security/performance/api-contract/migrations/adversarial conditionals selected; small, non-auth, non-mutating presentation-only diff)

## Findings and resolution

| # | Finding | Reviewer(s) | Severity | Resolution |
|---|---------|-------------|----------|------------|
| 1 | Dismiss button's `delegate()` call has swapped `type`/`selector` args — has never fired since this feature's 2026-06-09 introduction | julik-frontend-races | P2 (confidence 0.87) | **Fixed** — corrected to `delegate(bar, 'click', '[data-action="health-bar-dismiss"]', handler)`, matching all 5 other call sites in the file. Verified live: click now correctly adds `d-none`. Pre-existing, unrelated to B2. |
| 2 | New pending/degraded branch shipped with zero automated tests | testing | P2 (confidence 0.82) | **Fixed** — `tests/test_webui_feedback_states.py` already source-text-asserts against this exact file for other branches; added 4 tests following that pattern. |
| 3 | `'pipeline:never_run'` string duplicated between `health_projection.py` and `index.js` with no test tying them together | testing, maintainability (cross-reviewer agreement) | P2/P3 | **Fixed** — added `test_health_bar_never_run_literal_matches_backend`. |
| 4 | New plan doc missing required `claims:` frontmatter (post-2026-05-20 plans) | project-standards | P2 (confidence 0.78) | **Fixed** — added `claims: {}` (parked, no-implementation-yet plan; opt-out is the fitting form). Reproduced `plan-check` exit 8 -> exit 0. |
| 5 | Fetch resolution can silently un-dismiss the health bar if the user dismisses mid-request | julik-frontend-races | P3 (confidence 0.65) | **Deferred** — pre-existing, low-severity, recorded as backlog B5 in `docs/audits/2026-07-03-webui-feature-error-backlog.md`, not fixed this round. |
| — | Classification logic (`neverPublished`) exists only in JS, no shared field on the `/health` payload | agent-native | advisory | Not actioned — no functional gap today (an agent can already derive the same distinction from the unchanged `degraded_reasons` array); noted as a forward-looking DRY consideration if the reasons taxonomy grows. |
| — | SPA has no equivalent health-bar component yet | agent-native | advisory | Not actioned — tracked implicitly by the existing SPA migration status in `CLAUDE.md`; will need the same fix when `/` gets its SPA redirect. |

**Also discovered and fixed (not a reviewer finding, found during test verification):** running the touched test files together (rather than individually) surfaced the same `tests/webui/` vs. top-level `webui.py` module-name collision found and fixed in a separate worktree on 2026-07-03 (`ModuleNotFoundError`-adjacent `AttributeError: module 'webui' has no attribute 'app'`). This worktree branched from the same commit (`f835820e`) that introduced the collision. Applied the identical fix: renamed `tests/webui/` -> `tests/webui_conftest_poc/`.

## Cross-references confirmed clean

- correctness: no findings; verified `--info-soft` is a pre-existing token, `fetchJson` doesn't swallow the 503 "never published" response into `.catch()`, both `/` and `/ce:history` share the same template/JS.
- agent-native: PASS — `/health`'s `healthy`/`degraded_reasons`/503 contract is completely unchanged, so no agent-parity regression.
- learnings: no conflicting precedent; confirms this fix's classification logic already follows the "allowlist the safe case, not denylist the dangerous case" principle from a past incident (`docs/solutions/logic-errors/projector-silent-drop-status-vocabulary-drift-2026-05-26.md`); confirms no existing learning doc covers the CSS-token-reuse-vs-raw-literal decision (candidate for a future `/ce-compound` entry, not actioned here).
- julik-frontend-races: confirmed the three-way `classList.toggle()` sequence has no async race (all synchronous within one `.then()` callback before paint); confirmed `_initHealthBar()` is only ever called once (from `_boot()`), so no stale-response race from multiple invocations.

## Verification after fixes

- `tests/test_webui_health_routes.py`, `tests/test_webui_css_no_raw_colors.py`, `tests/test_webui_feedback_states.py` (excluding 7 pre-existing, unrelated `@_needs_node` failures caused by a Windows `cp950` subprocess-decoding issue, same territory as `fix/webui-windows-encoding-crash`): all green.
- `plan-check docs/plans/2026-07-06-001-feat-error-dashboard-stateblock-capture-plan.md`: exit 0.
- Live browser re-verification (isolated `webui.py` instance, fresh config dir): dismiss button now correctly hides the bar and sets `d-none`.
- Broader `tests/test_webui*.py` sweep surfaced 70 unrelated failures, spot-checked and confirmed to match already-documented, pre-existing Windows-only categories (NTFS `chmod` no-ops reporting `0o666` instead of `0o600`; stale SPA-redirect assertions expecting `200` where routes now correctly `302`) from `docs/audits/2026-07-02-u1-residual-failures.md` — none related to this diff.

**Verdict: Ready with fixes — all P2 findings resolved, one P3 deferred as backlog B5, both advisory notes accepted as forward-looking / non-blocking.**
