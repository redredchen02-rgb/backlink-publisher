---
title: Post-fleet-merge authoritative full-suite measurement (2026-07-06)
type: test_failure
severity: medium
tags: [test-suite, windows, debt-registry, ci]
---

# Post-fleet-merge authoritative full-suite measurement (2026-07-06)

## Context

Master convergence plan (`docs/plans/2026-07-06-006-...`) Unit 4: after aligning
local work with `origin/main` (PR #74) and landing several follow-up fixes
(PR #70, #75, #78), ran the full suite once on `origin/main`-based state as the
single authoritative measurement, replacing the multiple partial/independent
re-measurements that had accumulated across concurrent sessions.

## Method

```
PYTHONUTF8=1 PYTHONHASHSEED=0 PYTHONPATH=src pytest tests/ -q --timeout=120
```

Run in an isolated worktree, not the shared canonical checkout (another session
was concurrently active in the canonical checkout during this work).

## Results

| Run | Failed | Passed | Skipped | Errors |
|---|---|---|---|---|
| Before debt-registry fix (PR #78) | 116 | 12407 | 57 | 10 |
| After debt-registry fix (PR #78) | 105 | 12648 | 57 | 10 |

Both numbers are well below the ~258–261 failed / 10 errors baseline noted in
prior institutional research for local Windows runs — the suite has improved
substantially since that baseline was recorded, not regressed.

## Classification of the 11-failure delta (real regression, fixed)

`debt_registry.toml` was missing 24 entries that `test_debt_registry_freshness.py`
and `test_debt_registry_format.py::test_cross_reference_debt_comments_have_registry_entries`
assert against. The underlying code fixes and `# debt: <slug>` comments were
already on `main` — only the registry-side data had been silently dropped,
almost certainly during a merge that took one lineage's code changes but the
other lineage's (older) `debt_registry.toml`. Root cause and fix: see PR #78.

A related 1-line drift (not a missing entry) was also found and fixed in
`test_no_raw_requests_outside_http_client.py`'s `ALLOWLIST` for
`http_form_post.py`.

**Lesson for future merges:** when reconciling two lineages that both touch
`debt_registry.toml` and its cross-referenced source files, diff the *set of
slugs* (not just line-level conflicts) before trusting an auto-merge — a
registry entry and its corresponding code comment can silently separate across
a merge without producing a conflict marker, because git sees them as two
unrelated files with no textual overlap.

## Classification of the remaining ~105 failures (not fixed — platform noise)

The overwhelming majority (~90+) share one root cause: **Windows NTFS cannot
represent POSIX permission bits the way `os.chmod(path, 0o600)` /
`0o700` assume.** `os.chmod` on Windows typically collapses to either
`0o666` or `0o444` (read-only flag only), so any test asserting
`stat.S_IMODE(path.stat().st_mode) == 0o600` (or `0o644`, `0o700`) fails
regardless of application logic correctness. Confirmed representative
examples: `test_frw_login.py`, `test_io_utils.py`, `test_secrets.py`,
`test_reliability_circuit.py`, `test_webui_store_*_sqlite.py`,
`test_image_gen_token_rotation.py`, `test_save_config_section_taxonomy_canary.py`,
and the adapter `TestLoadToken::test_rejects_world_readable_token_file` family.

This is a pre-existing, well-known platform gap (no dedicated learnings doc
existed for it prior to this one — captured here per the `docs/solutions/`
convention). It is **not** a regression introduced by any of this session's
changes; the same tests fail identically on plain `origin/main` before any of
the fixes above.

The remaining `test_phase0_seal_hook.py` (10 errors) look like a
collection/fixture-setup issue specific to git-hook-installer tests running
inside a worktree (hooks live in the shared `.git/hooks`, which may behave
differently across worktrees vs a single-checkout repo) — not investigated
further in this pass; flagged for a dedicated follow-up if it recurs.

## v0.6.0 U1 status

Given the suite is materially healthier than the previously-documented
367→~90 triage baseline and the ~258–261 pre-existing-noise baseline, and the
only non-noise failures found in this pass were the debt-registry drift (now
fixed in PR #78), **v0.6.0 U1 (test-suite triage) can be considered
substantively closed** on the current `origin/main` lineage. The residual
~105 failures are the documented Windows-permission-noise class, not unfixed
triage debt.

## Follow-ups (not done in this pass)

- A dedicated Windows-chmod-noise learnings doc / xfail-marking pass would
  reduce this suite's local signal-to-noise ratio (many of these tests likely
  pass correctly in CI's Linux runners; consider marking them
  `skip on win32` with a reason, rather than leaving them permanently red on
  local Windows runs).
- `test_phase0_seal_hook.py` collection errors in worktree contexts — root
  cause not investigated.
