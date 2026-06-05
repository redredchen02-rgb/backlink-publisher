---
date: 2026-06-05
plan_id: 2026-06-05-006
title: Reliability-config consolidation + anchor ko-ratio calibration + llm-settings perm migration
status: completed
source_ideation: docs/ideation/2026-06-05-backlog-convergence-ideation.md (idea #5 bundle)
claims: {}
---

# Plan: Hardening bundle — circuit env clarity, ko-ratio calibration, llm-settings perms

## ⚠️ Execution sequencing constraint (read first)

All three target files are **currently clean** (outside the live agent's working
set): `publishing/reliability/circuit.py`, `publishing/reliability/policy.py`,
`anchor/resolver.py`, plus the llm-settings write path. **But** the live agent
holds a large uncommitted set in the shared canonical tree. Per memory
`git-mutation-in-shared-tree-collides` and `tmp-clone-not-safe-from-live-agent`,
**do not edit even clean files here until the tree settles** (merge-swarm
commit/reset would sweep uncommitted edits, and clones have been force-pushed
over). **Gate all three units on: live agent done + `PYTHONHASHSEED=0 pytest`
green.** Each unit is independently shippable (separate PRs preferred).

## Overview

Three confirmed, gate-free hardening residuals surfaced by the 2026-06-05 backlog
convergence. None depends on a killed/parked gate. Each is small but real; bundled
here for one planning pass, but ship as independent units.

## U1 — Reliability trip-threshold env clarity (investigate-first)

**Confirmed state (read-only):** there are **three** trip-threshold env vars across
two layers:
- `circuit.py:155` `_consecutive_errors_threshold()` reads
  `BACKLINK_PUBLISHER_CIRCUIT_CONSECUTIVE_ERRORS` (default `_DEFAULT_CONSECUTIVE_ERRORS`).
- `policy.py:64-66` reads `BACKLINK_PUBLISHER_CIRCUIT_AUTH_THRESHOLD` (default 3) and
  `BACKLINK_PUBLISHER_CIRCUIT_ERROR_THRESHOLD` (default 5).

**Why this is investigate-first, not a blind rename:** memory
`reliability-policy-circuit-facts` records that the *actual* live trip threshold is
`CIRCUIT_ERROR_THRESHOLD` (policy layer), and that this subsystem has a history of
dead code (the HALF_OPEN trial-limiter, since removed). So `circuit.py`'s
`CONSECUTIVE_ERRORS` may be a **legacy/secondary knob** that no longer gates the
live publish path — or it may gate a different (lockless state-machine) layer.

**Steps:**
1. Trace call sites: where is `_consecutive_errors_threshold()` actually consumed
   vs where `policy._threshold(_ERROR_THRESHOLD_ENV, …)` is consumed on the live
   `publish_with_policy` path.
2. Decide one of:
   - **(a) Redundant** → collapse to a single documented env var; keep a
     deprecation shim reading the old name with a warning for one release.
   - **(b) Distinct layers** → keep both but add module docstrings + a config-doc
     table making the layering explicit (which knob gates what), so operators stop
     confusing them.
3. Update `config.example.toml` / AGENTS.md env table to match the decision.
**Tests:** assert the live trip path reads the intended env; if a deprecation shim
is added, assert old-name → new-name fallback + warning.
**Effort:** M (investigation dominates). **Risk:** changing the live threshold knob
silently alters circuit behavior — keep defaults byte-identical; only rename/clarify.

## U2 — Anchor ko-ratio calibration (`_MIN_KO_HANGUL_RATIO`)

**Confirmed state:** `anchor/resolver.py:103` hardcodes `_MIN_KO_HANGUL_RATIO = 0.30`
with `TODO(ko-corpus-calibration): threshold=0.30 unvalidated against real ko`
(:100). Recurred across ideation R8/R9/R12 untouched. (R12 fixed the separate NFC
normalization bug — this threshold is independent and still open.)

**Steps:**
1. Either (preferred) measure the ratio over a small real ko-anchor corpus and set a
   justified constant with the corpus + rationale in a comment, OR — if no corpus is
   available — convert the magic number into a named, documented constant with its
   derivation and remove the TODO's "unvalidated" claim by stating the basis.
2. Add a diagnostic/log line when a borderline ratio (near the threshold) is hit, so
   future miscalibration is visible rather than silent.
**Tests:** boundary cases around the threshold (just-above / just-below) assert the
ko-detection verdict; diagnostic emitted on borderline.
**Effort:** S-M. **Risk:** low — pure classification threshold; defaults preserved
unless a corpus justifies a change (call that out explicitly if so).

## U3 — `llm-settings.json` one-time permission migration

**Confirmed state (partial):** CLAUDE.md trap + memory note: `~/.config/backlink-
publisher/llm-settings.json` must be `0o600`; writes now go through
`safe_write.atomic_write` (PR #140), but files written by pre-#140 code may still be
`0644`. No chmod-on-read migration found in the current code.

**Steps:**
1. On read of the llm-settings store, if the file exists and its mode is group/other
   readable, `chmod 0600` it once (best-effort, never crash on failure) and log the
   one-time fix.
2. Confirm the write path already enforces 0600 (it should via atomic_write); add a
   test if missing.
**Tests:** a 0644 fixture file is silently upgraded to 0600 on read; a 0600 file is
untouched; chmod failure (e.g., read-only FS) does not raise.
**Effort:** S. **Risk:** low — best-effort hardening; the api_key file is the asset.

## Cross-cutting
- Two-gate budgets (CLAUDE.md): if any new function is born over a SLOC/CC ceiling,
  raise it with ≥80-char rationale in the **same** change.
- Keep all defaults byte-identical (U1, U2) unless a measured corpus (U2) or a
  confirmed-dead knob (U1) justifies otherwise — and say so loudly if it does.

## Success criteria
- U1: one source of truth (or one clear doc table) for the circuit trip threshold;
  no operator can set a knob that silently does nothing.
- U2: no unexplained magic number in ko-detection; threshold has a stated basis +
  borderline diagnostic.
- U3: legacy 0644 llm-settings.json self-heals to 0600 on next read.
