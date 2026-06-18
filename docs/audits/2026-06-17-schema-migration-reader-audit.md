# Audit — #24-class half-migrated reader scan (Phase 0 U5)

Plan `docs/_archive/plans/2026-06-17-002-feat-activation-verify-gate-plan.md` R0.3.

**#24-class bug shape:** a schema migration (e.g. optimization-state v1→v2 nesting
`weights`/`stats` under a `"default"` language namespace) lands in the writer +
some readers, but one reader keeps consuming the old shape — silently producing
no-ops while shape-only tests stay green.

## Completeness criterion (NOT grep-as-proof)

grep is a **lower-bound** scan — a reader using a convention the patterns don't
match is invisible to it (the blind spot that hid #24 until PR #24). So this
audit **enumerates every versioned store and its readers by hand**, not just grep
hits. grep seeds (`version == 1/2`, `_upgrade_`, `.get(language`, `.get("default"`,
`data.get("weights")`) were run across `src/` and cross-checked against the manual
inventory below.

## The #24-class pattern: optimization-state v2 language namespace

This is the only store in the repo using the **double-layer language-namespace**
pattern that #24 exemplified. All readers of `optimization_state.json` (v2):

| Reader | File | Unwraps `"default"` namespace? | Status |
|--------|------|-------------------------------|--------|
| rule dispatch | `optimization/rules.py:58-64,85` | yes (`resolved_*`) | ✅ fixed in #24 |
| `get_weight` / `to_summary` | `optimization/state.py:131-137,281-282` | yes (`.get(language)`) | ✅ correct |
| keepalive status panel | `cli/keepalive_status.py:45-46` | yes (`.get("default")`) | ✅ fixed in #24 |
| dispatch override | `publishing/registry.py:563-574` | yes (`_find_weight` lang→default) | ✅ correct (locked by `test_optimization_e2e.py::test_full_cycle_drift_penalty`) |

**Conclusion: no new #24-class hit.** The one optimization-v2 consumer that PR #24
did not itself touch — `registry.py:dispatch_weight` — was inspected and already
unwraps the namespace correctly (and is asserted by a passing e2e test). U1's
regression lock (`TestV2NamespaceRegressionLock`) guards the engine side.

Non-store language-keyed lookups surfaced by grep — `plan_backlinks/_payload.py`
(template by language), `anchor/resolver.py` (ratio rules by language) — are
static-config lookups, not migrated state stores; not in scope.

## Other versioned stores (different versioning, NOT the #24 double-layer)

Enumerated for completeness. Each carries a `version`/schema marker but is
single-shape (no language-namespace double layer), so the #24 failure mode does
not apply. Spot-checked that each reader matches its writer's current shape; no
half-migration found. A deeper per-store audit is out of Phase 0's #24-class scope.

| Store | File | Versioning | #24-class risk |
|-------|------|-----------|----------------|
| events.db | `events/schema.py`, `events/store.py` | SQL schema upgrade | none (single schema; readers query by `kind`) |
| keepalive run-state | `keepalive/run_state.py` | dict `version` | none (flat) |
| footprint baseline | `footprint.py`, `cli/_footprint_baseline.py` | `version` | none (flat) |
| anchor profile | `anchor/profile.py` | `version` | none (flat) |
| channel-discovery decided | `channel_discovery/decided.py` | `version` | none (flat) |
| dual-state audit | `audit/readers.py` | snapshot reader | none (read-only) |

## Deferred (recorded, not a half-migration)

- `recheck-ledger-liveness-seam` (`debt_registry.toml`, opened by U4): a real
  output-seam gap (ledger liveness ignores dead `link.rechecked` verdicts), but
  **not** a schema half-migration — different class. Deferred to Phase 1.

## Outcome

- #24-class (language-namespace half-migration): **clean** — all optimization-v2
  readers verified, no new fix needed; engine guarded by U1 lock.
- No new `debt_registry.toml` half-migration entries required from this scan.
