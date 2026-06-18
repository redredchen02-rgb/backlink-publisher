# Runbook — Reliability observe→enforce rollout

Plan: `docs/_archive/plans/2026-06-15-006-feat-reliability-observe-to-enforce-plan.md`

The reliability policy has three modes, resolved from
`BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED`:

| Value | Mode | Behavior |
|---|---|---|
| unset / `0` / unrecognized | `off` | transparent passthrough (default) |
| `observe` | `observe` | run gates, persist `would_skip_*` decisions, **still dispatch** |
| `1` / `enforce` | `enforce` | actually skip — **but only for allowlisted channels** |

## Step 1 — Turn on observe (start measuring)

```
export BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=observe
```

Decisions now persist to `events.db` as `reliability.decision` events. Watch them
via `GET /ce:health/publish-metrics` → `readiness` (per channel) and `policy_mode`.

## Step 2 — Wait for the readiness verdict (do NOT skip this)

Enforce is **gated on data**. Per channel, `readiness.verdict` is one of:

- `insufficient_data` — too few attempts or too short a window. Keep waiting.
  (Brand-new observe shows this for ~the staleness window; expected.)
- `enforce_pointless` — enough data, but the gate ~never wants to fire. A real
  **negative conclusion**: do not enforce this channel.
- `enforce_worthwhile` — enough data AND would-skips present. Enforce will catch
  real skips.

Only a channel reading `enforce_worthwhile` is a candidate. Thresholds
(`DEFAULT_MIN_ATTEMPTS` / `DEFAULT_MIN_DAYS_OBSERVED`) are provisional — calibrate
against the real distribution before trusting the verdict.

## Step 3 — Enforce ONE channel (recommended first: mastodon)

`enforce` skips nothing until a channel is allowlisted. Add one:

```
export BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=enforce
export BACKLINK_PUBLISHER_RELIABILITY_ENFORCE_CHANNELS=mastodon
```

mastodon is the recommended first target: the only no-fallback channel that is
also browser-tier, so (a) its per-platform circuit breaker is honest (no
per-adapter work needed) and (b) it can produce `skipped_policy` evidence via the
health gate. Non-allowlisted channels stay in observe behavior.

**Acceptance vs value.** A fault-injected trip validates the *wiring* (covered by
`tests/test_reliability_enforce_seam.py`). The *value* criterion — enforce skipped
a publish a NATURAL trip (real ban / session-expiry / consecutive errors) would
have wasted — is an operational observation. Watch for a persisted
`skipped_circuit_open` / `skipped_policy` `reliability.decision` whose trip was
organic. If no natural trip occurs within a bounded window (e.g. N days), record a
negative-value conclusion (machinery validated, never exercised) and roll back.

## Rollback (single, safe)

Remove the channel from the allowlist; it returns to observe on the **next publish
run** (the allowlist is re-read per call, no restart needed):

```
export BACKLINK_PUBLISHER_RELIABILITY_ENFORCE_CHANNELS=   # or unset
```

To stop all policy behavior, set the mode back to `off` (or unset it).

## Failure mode — corrupt circuit state

The circuit state file (`<config_dir>/publish-circuit-state.json`) is fail-CLOSED:
a corrupt/unparseable file makes `is_tripped` return True for every platform. Under
**enforce** this is NOT treated as a real trip — the policy layer degrades the
affected channel to observe (dispatches once) and records a
`circuit_state_unreadable` `reliability.decision` so the corruption surfaces loudly
instead of silently halting the allowlist. The next state write (from that
degraded dispatch's outcome) overwrites the corrupt file, self-healing within ~one
attempt per channel. If you see `circuit_state_unreadable`, inspect/repair the file.

## Signal freshness (Plan 2026-06-15-007 — keeps the /health panel trustworthy)

The panel's liveness-coverage and selector-drift signals only stay accurate if the
schedules below run. (These feed the **panel**, not the enforce *verdict* — that is
would_skip-based and fresh on every publish.)

- **Install/refresh both agents**: `bash scripts/install-recheck-launchd.sh`
  (installs `com.dex.bp-recheck` + `com.dex.bp-selector-drift`).
- **Recheck — now DAILY** (`com.dex.bp-recheck.plist`, 04:30). Weekly could not
  *hold* ≥50% within-window coverage (`stale_days=30`) against publish inflow; daily
  within the ~600s probe-batch budget does. `run-recheck-periodic.sh` then runs
  `publish-metrics --alarm` and logs a WARN if coverage dropped below target.
- **Coverage alarm**: `publish-metrics --alarm` exits 6 when within-window coverage
  < target (default off / advisory). Run it ad hoc to check, or read the WARN in
  `logs/recheck.log`. No false alarm on an empty ledger.
- **Selector-drift — DAILY static check** (`com.dex.bp-selector-drift.plist`, 05:00
  → `run-selector-drift.sh`). Static manifest only (no browser): catches a
  selector/login constant deleted or mangled in-repo. It does **NOT** verify against
  the live sites — that is the attended `make selector-smoke` (needs an attached
  Chrome), which stays operator-run.

## Deferred (not in this rollout)

- Per-adapter circuit breaker (only matters for fallback-bearing channels; one
  fallback transition exists system-wide).
- Cross-mechanism fallback whitelist expansion.
