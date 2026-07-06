# Existing test-failure baseline — independent, read-only re-measurement (E1)

Date: 2026-07-06 · Plan: `docs/plans/2026-07-06-002-opt-hidden-debt-hardening-sweep-plan.md` (E1, Sprint E)
Scope: read-only re-measurement of failing tests on this branch, applying the clustering
methodology in `docs/solutions/test-failures/` (5 files) plus the adjacent CSRF false-green
doc in `docs/solutions/best-practices/`. **No test or source file was modified. No commit was
made.** This document is the only artifact produced by this unit.

## Coordination check performed (K1 / Concurrent Plan Coordination)

Before measuring, per the plan's explicit instruction, I checked the reconcile plan
(`2026-07-06-001-refactor-reconcile-github-gitlab-main-plan.md`) status. This branch
(`opt/hidden-debt-hardening-sweep`) was created from local `main` at `667e5cce`, which is a
descendant of the reconcile merge commit `d1ecbb1b` ("merge: reconcile origin/main (GitHub)
into local main — audited resolution") — so, narrowly, the premise "the base is already the
reconciled history, not pre-reconcile" is true.

**However, this check surfaced an important refinement worth recording**: `667e5cce` is only
two commits after `d1ecbb1b`, and local `main` has since moved substantially further
(11 commits ahead of this branch's fork point as of this writing, tip `77430167`), including
`763d0280` ("fix: stabilize reconciled tree — eliminate split-brain duplicates, Windows
compat, re-seed budgets"). That commit's own message states the reconcile merge alone caused
a regression ("~160 new local failures vs pre-merge baseline") and that stabilization brought
Windows unit-tier failures from **494 → 292**. `763d0280` is **not** an ancestor of this
branch's HEAD. Concretely, one of its fixes — guarding `os.O_NOFOLLOW` with `getattr` because
the constant doesn't exist on Windows — is absent here, and it alone reproduces as **42** of
the failures measured below (see Cluster 1). This is a real, evidenced example of the
"branch cut too early relative to a still-moving main" risk the plan's coordination table
warns about in the abstract; it does not invalidate this branch (E1 is read-only and does not
merge from main), but it does mean a chunk of what follows is "stale-relative-to-main
drift," not "novel defect," and should not be over-weighted as new debt to fix in this repo's
main line — it may already be moot there.

**A second, unplanned coordination event occurred during measurement itself**: at the start
of this unit the working tree had uncommitted changes (D2's `publishing/adapters/`
classification, already in progress). A concurrent session committed D2
(`a5f8ba3a`), then E2 (`23cb1061`, benchmark-only, additive), then E3 (`176865c0`,
`62d69e04`, docs-only) while Mode (a) below was running. This is expected, sanctioned
parallelism per the plan's own dependency graph (A/B/C/E series are independent and may run
concurrently) — not a conflict — but it does mean the two measurement modes below were not
taken against byte-identical trees. See the "Base commit" note under each mode for exactly
what was measured and why the mismatch is judged immaterial to the results.

## Base commits actually measured

- **Mode (a)** effectively measured tree content equivalent to commit **`a5f8ba3a`**
  ("fix(adapters): classify 56 except-Exception sites... (D2)"), not the branch tip at launch
  time (`45b4512a`). Reasoning: pytest's collection phase (which imports every test module)
  completes near the start of a serial run, before any dots are printed. D2's full diff was
  already present, uncommitted, on disk before this run was launched (confirmed via `git
  status` immediately prior), and its content did not change again before the run finished —
  the later `git commit` for D2 was a pure bookkeeping action mid-run, not a file-content
  change. A second concurrent edit (E2 adding new cases to `tests/test_benchmarks.py`, `mtime`
  ≈13:08:41) landed on disk *after* collection had already captured the old version of that
  file, so E2's new benchmark tests are simply absent from Mode (a)'s collected set — consistent
  with measuring at `a5f8ba3a`, prior to E2's commit `23cb1061`.
- **Mode (b)** was run against the clean, stable tip **`62d69e04`** ("docs(plan): mark E3
  complete"), captured immediately before launch and re-verified unchanged (`git status` /
  `git log -1`) immediately after both steps completed.
- The only content difference between the two effective bases is E2 (new, additive benchmark
  tests in `tests/test_benchmarks.py`, zero source changes) and E3 (a new docs file, zero code
  changes) — verified via `git show --stat` on both commits. Neither can change the pass/fail
  outcome of any test that exists in both snapshots. The two modes are therefore comparable
  for every test that isn't itself a new E2 benchmark case.

## Mode (a): xdist off, no reruns (exposes flaky/order-sensitive failures)

```bash
cd bp-hidden-debt-hardening-sweep
PYTHONPATH=src PYTHONUTF8=1 ../backlink-publisher/.venv/Scripts/python.exe -m pytest tests/ -m "unit" -q -rf --no-header
```

**Result:** `441 failed, 10163 passed, 40 skipped, 2234 deselected, 155 warnings, 10 errors in 332.66s (0:05:32)`

## Mode (b): CI-matching (verified against `.github/workflows/ci.yml`, `unit` job, both steps)

CI actually runs the unit tier as **two separate pytest invocations**, not one — a seam
subset without reruns, and the rest with reruns — so "matching CI precisely" means
reproducing both steps, not just the second one:

```bash
# Step 1 (seam — no reruns; ci.yml "Run unit tests (seam — no reruns)")
PYTHONPATH=src PYTHONUTF8=1 ../backlink-publisher/.venv/Scripts/python.exe -m pytest tests/ \
  -v --tb=short --timeout=15 -n auto -m "unit and seam" --strict-markers --strict-config -q -rf --no-header

# Step 2 (rest — reruns enabled; ci.yml "Run unit tests (rest — reruns enabled)")
PYTHONPATH=src PYTHONUTF8=1 ../backlink-publisher/.venv/Scripts/python.exe -m pytest tests/ \
  -v --tb=short --timeout=15 -n auto -m "unit and not seam" --strict-markers --strict-config \
  -q -rf --no-header --reruns 2 --reruns-delay 1
```

(`--cov`/`--cov-report=...` flags from `ci.yml` were omitted — they don't affect which tests
pass or fail and would have written a `coverage-unit.json` artifact into the repo, which this
read-only unit avoids.)

**Step 1 (seam) result:** `55 failed, 751 passed, 1 skipped, 55 warnings in 33.87s`
**Step 2 (not-seam) result:** `338 failed, 9460 passed, 40 skipped, 306 warnings, 10 errors, 696 rerun in 189.92s (0:03:09)`
**Combined CI-matching total:** **393 failed / 10211 passed / 41 skipped / 10 errors**

Step 2 also hit three `pytest-xdist` worker crashes (`[gwN] node down: Not properly
terminated`, workers `gw0`, `gw4`, `gw12`), each automatically replaced by xdist. This is an
additional, previously-undocumented instability observed during this measurement — worth a
follow-up look (candidate root cause: a test spawning a subprocess/browser resource that
kills its own worker), but out of scope to chase down under this unit's read-only mandate.

## Mode (a) vs Mode (b): not directly comparable — do not conflate

| | Mode (a) (serial, no reruns) | Mode (b) (CI-matching) |
|---|---|---|
| failed | 441 | 393 |
| passed | 10163 | 10211 |
| skipped | 40 | 41 |
| errors | 10 | 10 |
| wall time | 332.66s | 33.87s + 189.92s = 223.79s |

Mode (a) shows **48 more failures** than Mode (b). This is not noise — it is the
plan's own predicted effect, empirically confirmed: reruns mask transient failures, and
xdist changes worker/session-fixture isolation boundaries. One entire cluster (48 failures,
`TypeError: can't compare offset-naive and offset-aware datetimes`, see Cluster 4 below) is
present in Mode (a) and **completely absent** from Mode (b) — a striking, concrete
illustration of why the plan explicitly forbids treating a single run as "the" CI-comparable
number.

## Root-cause clustering (not 393–441 independent problems)

Applying the audit recipes from `docs/solutions/test-failures/` (`rg` for `has no
attribute`/`AttributeError`/`TypeError` signatures, then reading representative tracebacks)
shows the failures cluster into a handful of shared root causes, matching the family's
central claim ("the same root cause recurs across dozens of superficially unrelated test
files"). Counts below are from Mode (a); all four clusters were independently confirmed
present in Mode (b) too (grep counts per cluster shown), except Cluster 4, which is the one
cluster Mode (b) does not reproduce.

### Cluster 1 — `AttributeError: module 'os' has no attribute 'O_NOFOLLOW'` (42 failures)

`src/backlink_publisher/_util/secrets.py:211` does `os.open(lock_path, os.O_RDWR |
os.O_CREAT | os.O_NOFOLLOW, 0o600)` — `O_NOFOLLOW` doesn't exist on Windows' `os` module.
**Already fixed on `main` at `763d0280`** (`nofollow = getattr(os, "O_NOFOLLOW", 0)`), which
is not an ancestor of this branch (see Coordination section above). Windows-only; would not
reproduce on `ubuntu-latest` CI. Confirmed present in Mode (b): 1 (seam) + 41 (not-seam) = 42.

### Cluster 2 — `AttributeError: 'Config' object has no attribute 'token_path'` (47 failures, 15 files)

A genuine, real bug — **present on this branch AND on current `main` tip (`77430167`)**, so
this is not reconcile/staleness drift, it is previously-undocumented live debt. Fifteen
adapter source files (`linkedin_api.py`, `ghpages.py`, `gitlabpages.py`, `devto_api.py`,
`hackmd_api.py`, `hashnode_graphql.py`, `mataroa_api.py`, `notion_api.py`, `qiita_api.py`,
`tumblr_api.py`, `wordpresscom_api.py`, `writeas_api.py`, `zenn_github.py`,
`_setup_checks.py`, `_verify_live.py`) call a generic `config.token_path("<platform>")`
method. `src/backlink_publisher/config/types.py`'s `Config` dataclass only exposes
**per-platform properties** (`ghpages_token_path`, `linkedin_token_path`, `devto_token_path`,
...) — there is no generic parameterized `token_path()` method anywhere in `config/`. This
would fail identically on Linux CI; it is not Windows-specific. Confirmed present in Mode (b),
all 47 in the not-seam step (0 in seam).

### Cluster 3 — `pytest_socket.SocketBlockedError` (92 failures, ~26 files)

Real network calls reach `socket.getaddrinfo` and get blocked by `pytest-socket`, meaning a
test's mock no longer intercepts the call it's supposed to. Traced one concrete instance
(`test_channel_probe_ssrf.py`) to `_util/http_probe.py` now routing through a pooled
`_get_session()` object instead of calling `requests.get` directly — tests still `patch
"requests.get"`, which the pooled-session code path bypasses entirely. `763d0280` on `main`
fixed exactly this for `test_channel_probe_ssrf.py` ("mock `http_probe._get_session`... probe
now uses pooled session"), but the same underlying pattern reaches far more files here
(dedup/publish/content-fetch flows), so this branch's exposure is broader than what that one
upstream commit addressed. Confirmed present in Mode (b): 37 (seam) + 162 (not-seam) = 199 —
note the count is *higher* under xdist/reruns here, the opposite direction from Cluster 4,
underscoring that mode-to-mode deltas cut both ways and can't be assumed to point one
direction.

### Cluster 4 — `TypeError: can't compare offset-naive and offset-aware datetimes` (48 failures — Mode (a) only, 0 in Mode (b))

A real bug in a shared scheduling helper (`calc_next_available`-shaped function reachable
from many webui route-rendering tests, e.g. `test_r6_dofollow_badge.py`): parses timestamps
via `datetime.fromisoformat`/`strptime` (naive) from `drafts_store`/history, then calls
`max(requested_dt, earliest)` against a timezone-aware `requested_dt`. Reached through many
unrelated-looking test files because they all render a page/context that touches this helper.
**Zero occurrences in either Mode (b) step** — the single clearest empirical demonstration in
this dataset of why Mode (a) and Mode (b) are not interchangeable numbers.

### Smaller, previously-documented clusters

- **10 errors, both modes, identical** — `tests/test_phase0_seal_hook.py` fixture shells out
  to `scripts/install-pre-push-hook.sh` via `bash`, exit 127 under this Windows Git-Bash/PATH
  interop. This is an **exact match** to the U1 residual doc's documented pre-existing,
  Windows-only, CI-irrelevant error class (see cross-reference below).
- **`test_no_monolith_regrowth.py` (9 failures)** — three files have grown past their tracked
  SLOC ceiling since B1/B2 last ran (`webui_store/channel_status.py` SLOC 311 > ceiling 310;
  `webui_app/routes/health.py` SLOC 592 > ceiling 490; `webui_app/health_metrics.py` SLOC 774
  > ceiling 370). Self-diagnosing failure messages ("Should have been caught by
  test_sloc_within_ceiling. Likely a measurement error in the seed PR.") — budget-drift
  category, distinct from the test-pollution families this unit's methodology targets.
- **`test_debt_registry_freshness.py` (10 failures)** and **`test_cli_plan_check.py`'s
  `TestValidateShaFormat` (8 failures, via `AttributeError: has no attribute
  '_validate_sha_format'`)** — both look like the same lazy-export/reconciliation-artifact
  shape as Cluster 2 (a helper the tests expect isn't exposed where they expect it), most
  plausibly downstream of the `cli/plan/plan_check.py` reconciliation described in
  `docs/audits/2026-07-06-cli-decomposition-reconciliation-audit.md`. Not chased to a fix
  under this unit's read-only mandate.

Rough coverage: Clusters 1–4 plus the two error/budget clusters above account for
**≈267 of 441** Mode (a) failures (~61%) under only five/six root causes — empirically
confirming the plan's premise that this is not hundreds of independent bugs.

## Audit-recipe results (docs/solutions/test-failures/ methodology, applied repo-wide)

All five read (`ci-test-isolation-failures-medium-brave-sleep-timeout-2026-05-13.md`,
`del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md`,
`inverted-negative-assertion-enshrined-config-save-data-loss-2026-05-14.md`,
`negative-assertion-locks-in-bug-2026-05-15.md`,
`tests-coupled-to-operator-config-state-2026-05-18.md`), plus two adjacent docs the
methodology explicitly points at: `pyyaml-int-coerces-all-digit-sha-2026-05-20.md`,
`strict-markers-addopts-noop-conftest-module-load-2026-06-01.md` (both physically in the same
directory — 7 files total there today, not 5; also read
`docs/solutions/best-practices/app-level-csrf-guard-makes-blueprint-csrf-dead-code-2026-05-27.md`,
named by the plan's Context section as part of this same family).

```bash
rg 'assert .* not in ' tests/                                        # 711 hits
rg 'del os\.environ|del _os\.environ' tests/                         # 11 hits (10 are docstrings/comments)
rg 'assert.*stderr.*==.*""' tests/                                   # 3 hits
rg 'assert len\(.*\) == 0' tests/                                     # 17 hits
rg -E 'def test_.*(does_not|must_not|should_not|is_read_only|is_dropped|is_ignored)' tests/   # 187 hits
```

- **`del os.environ` (11 hits)**: 10 are documentation/comments *warning against* the pattern
  (in `conftest.py` and three test docstrings) — the fix from the 2026-05-27 incident has
  held. The one real `del os.environ[...]` call (`tests/test_oauth_service.py:53`) manages an
  unrelated, test-owned env var (`OAUTHLIB_INSECURE_TRANSPORT`-style `_OAUTH_ENV`) that the
  same test set moments earlier — it is not `BACKLINK_PUBLISHER_CONFIG_DIR`, and it doesn't
  cross into the session-scoped isolation fixture's territory. **No live instance of this
  pattern found.**
- **`stderr == ""` (3 hits)**: all three are in `tests/test_plan_backlinks.py`, which does
  **not** appear in either mode's failure list — this specific always-on-signal risk is not
  currently triggering.
- **`does_not`/`must_not`-named tests**: 15 of the 441 Mode (a) failures are themselves named
  with this shape (e.g. `test_medium_brave_failure_does_not_fall_to_browser`,
  `test_verify_does_not_modify_token_file`). Important scoping note: the
  negative-assertion-locks-in-bug pattern specifically describes a test that stays **green**
  while enshrining a bug — by definition it cannot be found by scanning the **failing** set,
  since a currently-red test isn't silently masking anything. These 15 are red because of the
  same environment/API-mismatch clusters above (e.g. several are `test_adapter_dispatcher.py`
  cases failing on the `BloggerAPIAdapter` lazy-init `AttributeError`, unrelated to their own
  assertion polarity), not because their negative assertion inverted. A full audit for this
  family (scanning the ~10,163 **passing** tests for negative-shape assertions that might be
  silently enshrining something) is a materially larger undertaking than this pass covers and
  is a good candidate for a dedicated follow-up, not attempted here.
- **`assert .* not in ` (711 hits)** and **`len(...) == 0` (17 hits)**: not individually
  triaged against the failing set given time budget — flagged as a follow-up if a future unit
  wants to run the full per-hit "would this go red if the negative behavior were correct?"
  question from the docs.

## Cross-reference against v0.6.0 U1's residual-failure list

`docs/audits/2026-07-02-u1-residual-failures.md` is referenced by the plan but **does not
exist in this branch's history** — it was added by commit `26e7aca4` on `fix/u1-test-suite-triage` /
`main`, and that commit is not an ancestor of this branch (branched too early, same root
cause as the Coordination section above). Its content was read via `git show
26e7aca4:docs/audits/2026-07-02-u1-residual-failures.md` (read-only, does not modify this
worktree). That document's own baseline was measured at SHA `56b98084` — a materially older,
pre-this-branch, pre-many-things point in history — so "matches / new / resolved" below is a
qualitative file-level comparison, not an apples-to-apples number-for-number diff.

U1 named ~35 specific files/clusters as residual. Checked each by name against Mode (a)'s
failing-file list:

**Matches (31 of 35 named files still fail here today):** `test_secrets.py`,
`test_image_gen_token_rotation.py`, `test_save_config_section_taxonomy_canary.py`,
`test_canary_store.py`, `test_comment_outreach_status_store.py`, `test_credential_service.py`,
`test_registry_credential_saver.py`, `test_cli_health_check.py`, `test_config_llm_sidecar.py`,
`test_dedup_digest.py`, `test_dedup_connection.py`, `test_reliability_circuit.py`,
`test_webui_llm_test_persist.py`, `test_provider.py`, `test_settings_service.py`,
`test_purge_removed_credentials.py`, `test_dedup_operator_verbs.py`,
`test_dedup_adjudicate.py`, `test_dedup_force_manifest.py`,
`test_reliability_circuit_crossproc.py`, `test_io_atomic_crossproc.py`,
`test_idempotency_backfill.py`, `test_frw_login.py`, `test_fail_closed_resolver.py`,
`test_no_raw_home_path_primitives.py`, `test_no_inner_import_shadowing.py`,
`test_cli_exit_code_literals.py`, `test_config_managed_root_subsection_roundtrip.py`,
`test_config_echo.py`, `test_no_raw_requests_outside_http_client.py`,
`test_public_facade_resolvable.py` (still one of U1's two flagged "real bugs, not fixed" —
facade shadowing, per its description still not attempted), plus `test_benchmarks.py`
(U1's other flagged real bug, `test_benchmark_publish_50_rows_dry_run` — stale fixture payload
— still failing, present in Mode (b) not-seam).

**Not currently reproducing (4 of 35 — likely flaky-run-luck, not resolved):**
`test_cli_recheck_backlinks.py`, `test_config_safety_net.py`, `test_safe_write_substrate.py`,
and `test_phase0_seal_hook.py` (this last one is not "resolved" — it still errors, just
categorized by pytest as an ERROR rather than a FAILED, matching U1's own "10 ERRORs" count
exactly). U1's own doc already flagged the first three as clock-granularity-collision flakes
that "flip pass/fail run to run" — this is consistent with that documented flakiness, not a
fix landing on this branch.

**New (not named by U1, found only in this pass):** Cluster 1 (`O_NOFOLLOW`, 42 — postdates
U1's `56b98084` baseline; introduced/exposed by the later reconcile merge), Cluster 2
(`Config.token_path`, 47 — a previously-undocumented real bug), Cluster 3
(`SocketBlockedError`/pooled-session mocking gap, 92 — also postdates U1, same reconcile-merge
origin as Cluster 1), Cluster 4 (offset-naive/aware datetime, 48 — new), and the
`test_debt_registry_freshness.py` / `TestValidateShaFormat` lazy-export cluster (18). None of
these existed in U1's `56b98084` snapshot; all five are plausible downstream consequences of
the reconcile merge (`d1ecbb1b`) and the subsequent `763d0280`-vs-this-branch staleness
already documented above, rather than genuinely new hand-written bugs introduced by this
plan's own A/B/C/D1 units.

## Reproducibility summary

| | Command | Base SHA | Result |
|---|---|---|---|
| Mode (a) | `PYTHONPATH=src PYTHONUTF8=1 pytest tests/ -m "unit" -q -rf --no-header` | effectively `a5f8ba3a` (see note above) | 441 failed / 10163 passed / 40 skipped / 2234 deselected / 10 errors |
| Mode (b) step 1 | `pytest tests/ -v --tb=short --timeout=15 -n auto -m "unit and seam" --strict-markers --strict-config` | `62d69e04` | 55 failed / 751 passed / 1 skipped |
| Mode (b) step 2 | `pytest tests/ -v --tb=short --timeout=15 -n auto -m "unit and not seam" --strict-markers --strict-config --reruns 2 --reruns-delay 1` | `62d69e04` | 338 failed / 9460 passed / 40 skipped / 10 errors / 696 rerun |

All runs: Python 3.11.14, `pytest 9.1.1`, `pytest-xdist 3.8.0`, `pytest-rerunfailures 16.4`,
`pytest-timeout 2.4.0`, venv at `../backlink-publisher/.venv`. `PYTHONHASHSEED=0` applied via
`pytest-env` per `pyproject.toml`.

## What this unit did not do

No test or source file was modified. No fix was attempted for any cluster above (including
the two genuine, previously-undocumented real bugs in Clusters 2 and 4) — that is explicitly
out of scope for E1 per K1 and the plan's Test Expectation ("none — 純唯讀量測與報告產出"). No
`git add` or commit beyond this report file was performed. Full suite runs were limited to
exactly the two specified unit-marked modes; no integration/e2e tier was run.
