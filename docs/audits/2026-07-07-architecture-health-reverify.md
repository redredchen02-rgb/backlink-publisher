---
title: "Architecture health re-verify (Unit 1 of opt/backend-code-health)"
date: 2026-07-07
type: audit
status: reference
verdict: mostly-unchanged, one live CI gate found broken
---

# Architecture health re-verify (2026-07-07)

Re-checks the 4 findings from `docs/solutions/architecture-health-audit-2026-06-01.md`
against the current worktree (`bp-backend-code-health`, branch `opt/backend-code-health`,
based on `main@85a9e1a7`), plus a fresh import-linter run.

## Finding-by-finding verdict

### #1 — `webui_store` imported by backend modules — **still valid, blast radius grew**

`grep -rl "webui_store" src/` now returns **12** matches (was 8 on 2026-06-01):
`audit/readers.py`, `canary/store.py`, `cli/publish/dispatch_backlinks.py`,
`cli/_bind/_driver_impl.py`, `cli/_publish_cli.py`, `cli/_resume.py`,
`events/history_importer.py`, `ledger/sources.py`,
`publishing/adapters/medium_browser.py`, `publishing/adapters/medium_liveness.py`,
`publishing/browser_publish/dispatcher.py`, `publishing/reliability/policy.py`.
Same shared-JSON-persistence-layer pattern as before, just more call sites accreted
since June. **Verdict: still intentional design, not a regression** — but the growing
blast radius (8→12) means a future rename would be even more expensive than the
audit doc estimated. No action taken here (out of scope for this unit).

### #2 — 5 `webui_app/` top-level files, incl. `medium_login.py` re-export shim — **still valid, unchanged**

Same file set present: `binding_status.py`, `health_metrics.py`, `scheduler.py`,
`medium_liveness.py`, `medium_login.py`. Read `medium_login.py` — still an explicit
16-line re-export shim with a docstring pointing at the canonical
`backlink_publisher.publishing.adapters.medium_auth`. **Verdict: unchanged, no dead code.**

### #3 — `_report_engine` in-process seam — **changed (moved), same intent**

The audit's cited call site, `webui_app/api/pipeline_api.py:452` doing
`from backlink_publisher.cli._report_engine import report_from_profile`, is gone.
`webui_app/api/pipeline_api.py` is now itself a 16-line re-export shim
("plan 2026-06-22-001 U5a") pointing at `backlink_publisher.sdk.api`. The real
in-process CLI-core call now lives at `src/backlink_publisher/sdk/api.py:471`:
`from backlink_publisher.cli.publish._report_engine import report_from_profile`
(the module itself relocated under `cli/publish/` per "plan 2026-06-24-002 U8", leaving
`cli/_report_engine.py` as a backward-compat shim re-exporting from the new location).
**Verdict: same architectural seam (thin-WebUI in-process call), just formalized one
layer down through `sdk.api`, which is exactly the pattern the `sdk.* -> cli.*`
ignore-list category exists for.** However, see the import-linter section below —
the specific ignore-list string was not updated when the module moved, and this is
a live, currently-broken CI gate, not just a stale doc reference.

### #4 — `cli/lease_management.py` orphan — **already resolved**

`src/backlink_publisher/cli/lease_management.py` does not exist in this worktree.
Confirmed via direct path check — no further action needed.

## Import-linter re-run

Command (from `pyproject.toml`'s `[tool.importlinter]`, invoked the way CI does it,
`.github/workflows/ci.yml:157` runs bare `lint-imports`; here run explicitly with
`PYTHONPATH` set since the venv is shared across worktrees):

```
cd bp-backend-code-health
PYTHONPATH=".;src" lint-imports.exe --config pyproject.toml
```

**Result: the check does not run at all — it aborts immediately with:**

```
No matches for ignored import backlink_publisher.sdk.api -> backlink_publisher.cli._report_engine.
```
(exit code 1)

Root cause: this is the exact `sdk.* -> cli.*` ignore-list entry the plan mentions,
but its target string is now stale. `sdk/api.py:471` imports
`backlink_publisher.cli.publish._report_engine` (post-move), not
`backlink_publisher.cli._report_engine` (the pre-move path, now just a compat shim
module). import-linter validates that every `ignore_imports` entry matches an actual
import edge in the graph before running any contract, and fails hard if one doesn't —
so this one dangling string currently **breaks `lint-imports` entirely**, for anyone
who runs it, including CI's `ci.yml:154-157` step.

This is a **new, currently-broken CI gate**, not a new architectural violation — the
underlying import (`sdk.api -> cli.publish._report_engine`) is the same, intended,
already-accepted `sdk.* -> cli.*` pattern; only the ignore-list string needs updating
to track the module's post-move path. It was almost certainly introduced by the
`cli/_report_engine.py` → `cli/publish/_report_engine.py` move (plan
2026-06-24-002 U8) without a corresponding `pyproject.toml` update.

### What the other 3 declared exceptions look like

Checked directly against source (not via the linter, since it can't run past the
stale entry above):

| Ignore-list entry | Actual import found in source | Status |
|---|---|---|
| `publishing.adapters.instant_web -> cli._bind.chrome_backend` | `publishing/adapters/instant_web.py:23` | matches, valid |
| `sdk._publish_runtime -> cli.publish_backlinks` | `sdk/_publish_runtime.py:209` | matches, valid |
| `sdk._publish_runtime -> cli._publish_helpers` | `sdk/_publish_runtime.py:242` | matches, valid |
| `sdk.api -> cli.plan_backlinks._engine` | `sdk/api.py:289` | matches, valid |
| `sdk.api -> cli._report_engine` | actual target is `cli.publish._report_engine` (`sdk/api.py:471`) | **stale — mismatch, breaks the linter run** |
| `keepalive.chain -> sdk.api` | not independently re-verified (unrelated to this crash) | assumed valid, unchanged |

Additionally, `sdk/_publish_runtime.py:318` imports
`backlink_publisher.cli.publish_backlinks._engine` (a submodule), which is a distinct
import edge from the ignore-listed `backlink_publisher.cli.publish_backlinks` — worth
confirming this doesn't need its own explicit ignore-list line once the stale entry
above is fixed and the linter can actually run again.

To see past the crash, a locally-patched copy of the `[tool.importlinter]` config
(ignore string corrected to `cli.publish._report_engine`, scratch-only, not committed)
was run to sanity-check the rest of the ruleset:

- **"Domain packages must not import from cli/"**: KEPT (passes) once the stale
  string is corrected.
- **"_util must not import from domain or cli"**: **BROKEN** — several transitive
  violations surfaced (`_util.paths -> config -> ... -> publishing.adapters.instant_web
  -> cli._bind.chrome_backend`, and similar chains reaching `optimization`, `content`,
  `events`, `linkcheck` via `config._toml_utils -> publishing.registry -> ...`). This
  contract's `ignore_imports` list is currently empty, so none of these transitive
  paths are whitelisted for *this* contract even though the underlying edges (e.g.
  `instant_web -> chrome_backend`) are already accepted under the *other* contract's
  ignore-list. Because the real config never gets past the stale-string crash above,
  this second contract's breakage has been silently unexercised by CI for an unknown
  period — it is not new, just newly visible.

**Comparison to the 3 documented exceptions**: no *new* architectural violations were
found beyond what's already accepted design (webui_store, `_report_engine`/`sdk.api`
seam, re-export shims). The concrete, actionable problem is narrower and mechanical:
one stale ignore-list string breaks `lint-imports` outright, and once patched, exposes
a pre-existing (not newly introduced) `_util`-contract breakage that was being masked
by the crash. Both are follow-up items for a later unit — not fixed here per this
unit's scope (audit/report only, no source or `pyproject.toml` edits).

## Summary table

| # | Finding | 2026-06-01 verdict | 2026-07-07 verdict |
|---|---|---|---|
| 1 | `webui_store` backend coupling | intentional design | still intentional; blast radius 8→12 files |
| 2 | 5 webui_app top-level files | active, no dead code | unchanged |
| 3 | `_report_engine` seam | intentional in-process seam | same intent, moved under `sdk.api`; ignore-list string not updated — breaks `lint-imports` |
| 4 | `cli/lease_management.py` orphan | real dead code, action item | already resolved (file removed) |

Net: 3 of 4 original findings hold up as before; the 4th (dead code) is confirmed
resolved; and re-running the linter surfaced one live, CI-blocking config drift plus
one masked pre-existing `_util` contract violation — both worth a follow-up unit to
fix `pyproject.toml`'s `ignore_imports` list.

## Addendum (post-unit, applied fix + second anomaly found)

The stale `sdk.api -> cli._report_engine` ignore-list string above was corrected in
`pyproject.toml` (now `sdk.api -> cli.publish._report_engine`) as part of this same
branch — a one-line, low-risk, high-value fix (it was breaking `lint-imports`
outright for anyone who ran it, including CI). Verified: `lint-imports` (run with
`PYTHONPATH=src` to work around the [[per-worktree-venv]] gotcha, and
`PYTHONUTF8=1 PYTHONIOENCODING=utf-8` to work around a Windows `cp950` console
codec crash on the banner art) now runs to completion instead of aborting.

However, the real (non-scratch) run surfaces a **second, more concerning anomaly**:
only the first of the two declared `[[tool.importlinter.contracts]]` entries
("Domain packages must not import from cli/") appears in the report at all —
`Contracts: 1 kept, 0 broken`. The second contract ("_util must not import from
domain or cli") is silently absent: not KEPT, not BROKEN, not listed as invalid.
This contradicts this doc's earlier finding (above) that the second contract is
"BROKEN" with specific transitive violations — that finding came from a scratch,
non-tool-invoked analysis and should be treated as unverified until the real CLI
actually reports on that contract.

Root cause not identified within this unit's scope (ruled out: TOML parses both
contracts correctly via `tomllib`; `read_user_options()` returns both in
`contracts_options`; cache-clearing and `--no-cache` don't change the result). This
looks like either an import-linter 2.12 quirk specific to two `type = "forbidden"`
contracts in one pyproject.toml, or something else that needs a maintainer-level
dig into `importlinter.application.use_cases._build_report`'s per-contract loop.
**Flagging as a follow-up item, not fixing here** — this is a tooling-visibility gap
(a contract that may or may not be silently never-enforced), not a newly introduced
architecture problem, and diagnosing it further is disproportionate to this audit
unit's scope.
