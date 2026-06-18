# Runbook — activation readiness (Phase 0 U6)

Plan `docs/_archive/plans/2026-06-17-002-feat-activation-verify-gate-plan.md` R0.2.

**Before activating any "built-but-unrun" subsystem** (flipping enforce mode,
loading a launchd plist, scheduling a probe), run this check. It closes the #24
gap: a subsystem's integration test was *plain red but tolerated*, masking a
silent no-op.

## The rule

A subsystem may be activated **only when its integration tests actually pass
(green)** — not merely "have no skip marker". A red test, with or without a
`# debt:`/`reason=` ref, **blocks activation of that subsystem**. A debt-ref only
keeps the red visible; it does not unlock activation.

## Pre-flight per subsystem

```bash
# 1. Tripwire: no subsystem test file is hidden (whole-file skip / collected==0 /
#    untracked skip-xfail). Fails loudly if a subsystem's tests can vanish.
PYTHONPATH=src pytest tests/test_activation_readiness_tripwire.py -q

# 2. The subsystem itself is GREEN (this is the activation gate). Either run the
#    files directly, or call the exported helper:
PYTHONPATH=src python -c \
  "import sys; sys.path.insert(0,'tests'); \
   from test_activation_readiness_tripwire import assert_subsystem_green; \
   assert_subsystem_green('weights')"   # or: citation | enforce | recheck
```

`assert_subsystem_green(name)` runs that subsystem's test files and raises if any
test is red — exit non-zero blocks the activation step.

## Subsystem → tests (source of truth: tripwire `SUBSYSTEMS`)

| Subsystem | Tests | Activation it gates (Phase 1) |
|-----------|-------|-------------------------------|
| weights | `test_optimization_e2e.py`, `test_cli_weights.py` | schedule `com.dex.bp-weights.plist` (R4) |
| citation | `test_cli_probe_citations.py` | schedule `com.dex.bp-citations.plist` (R3) + live run |
| enforce | `test_reliability_enforce_seam.py`, `test_reliability_decision_events.py` | flip enforce allowlist (R1) |
| recheck | `test_cli_recheck_backlinks.py`, `test_recheck_events_io.py` | (already scheduled; verify before relying on decay) |

## Shelf-life

If activation lags Phase 0 verification by **> 2 weeks**, re-run both pre-flight
steps for that subsystem before activating — the gap is a window where another
half-migration could land (Phase 0 plan, Operational Notes).
