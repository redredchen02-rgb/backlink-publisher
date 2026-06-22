# ce:review run — v0.5.0 UI consistency (U2/U3/U4)

- Mode: autofix · Branch: feat/v050-ui-consistency · Base: 09cc33c8 (main)
- Scope: 16 files (+1517/-69); reviewable code+tests ~900 lines (2 docs are protected artifacts)
- Reviewers (6, haiku): correctness, project-standards, julik-frontend-races, maintainability, testing, adversarial
- Verdict: **Ready with fixes applied** — 4 safe_auto fixes landed, suite green (1706 webui passed).

## Applied safe_auto fixes (4)
1. [P2] settings.js `_initExtensionFilter` — removed `noMatchRendered` once-guard; empty-state now re-renders with the live query (was: stale previous search term). Confirmed by correctness + julik-frontend-races + testing.
2. [P3] index.js `showFilteredEmpty` — dropped `filteredEmptyRendered` flag; renderEmpty (idempotent via replaceChildren) re-runs each empty filter.
3. [P1] ui/errors.js `_statusOf` — coerce `Number(x.status)` so a stringified `{status:"500"}` classifies as `server`, not `unknown` (adversarial).
4. [P1] tests/test_webui_css_no_raw_colors.py — `RAW_LITERAL` regex now also catches `hsl()/hsla()` (closes a token-gate bypass; 0 hsl in core CSS → no ceiling change).

## Always-on results
- **project-standards: ZERO anti-rot violations** (no inline on*, no window.* API, no untrusted innerHTML, readCsrf per-call, all 3 new tests carry `__tier__`).
- correctness: classifyError/null-guards/retry/has_channels all verified correct besides the flag bug.

## Residual actionable work (NOT auto-applied — downstream-resolver / human)
- [P1 gated] index.js HAS_CHANNELS=false when `__indexBootstrap` injection fails/races → wrong zero-config CTA for users WITH channels. Defensive fallback (data-attr or guard) suggested. (adversarial 0.80). Low likelihood (inline server bootstrap), left for judgment.
- [manual] Behavioral JS tests: the 3 new test files use STATIC source-string assertions (no JS test runner in CI). Behavioral/DOM tests (zero-config vs has-config branch execution, error-path catch firing, callback addEventListener binding) need a node/jsdom harness. (testing reviewer, multiple).
- [manual] Positive zero-channel sidebar test: `#sidebarChannelsEmpty` slot is rarely reached (anon channels always count as bound) — add a test mocking empty `active_platforms()` to prove it's not dead code. (maintainability + U2 self-flag).
- [advisory] Maintainability: 3 parallel empty-state initializers (index `_initEmptyState`+`showFilteredEmpty`, settings `_initChannelEmptyState`) could share a helper; `.btn-app-*` vs legacy `.btn-primary` duplication in fast-follow pages; CSS-ceiling rationale-enforcement test.

## Pre-existing (not this diff)
- monitor_hub.js `load()` has no AbortController/in-flight guard → concurrent refresh clicks can render out-of-order. Predates U4 (U4 only changed the error-message source). Worth a follow-up.
- `tests/test_webui_store.py::TestDraftsStore::test_insert_first_prepends` is a non-deterministic test-isolation flake (passes isolated, fails in some orderings) — relevant to R10's "full suite green" release gate.
