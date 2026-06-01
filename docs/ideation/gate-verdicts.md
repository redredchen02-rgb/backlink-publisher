---
date: 2026-06-01
topic: gate-verdicts
type: synthesis
status: active
plan: docs/plans/2026-06-01-005-feat-gate-first-validation-and-deficit-overlay-plan.md
---

# Phase-0 Falsification-Gate Verdict Ledger

> **Soft-fold note.** This is the interim single decision surface for the Phase-0
> gate verdicts. When the architecture-suite A2 ledger (`docs/ideation/SYNTHESIS.md`,
> plan 2026-06-01-003) ships, the owner of that plan folds these rows into its
> **Tried / Open** tables and leaves a back-reference here. Until then this file
> is authoritative (consol. R3 — reuse the ideation ledger, don't build a new
> file system; the soft-fold honors that without a hard dependency on unshipped A2).

## Governance rule (consol. R16) — read before adding any build-out plan

> **A "build a Phase 1–N machine" brainstorm may not enter `/ce:plan` until its
> cheap falsification gate returns `GO`.** Pure-read detection / probes / refactors
> are exempt. A `KILL` permanently parks the downstream Program stage; an
> `INCONCLUSIVE` must resample (never default to GO); a `BLOCKED` (Tier-2
> credentials unavailable) parks the stage until credentials exist.

## ⛔ KILLED premises (do not revive)

| Premise | Why killed | Date |
|---|---|---|
| `entropy-budget-footprint-diversification` | Operator `<a>` bytes never reach the crawled page — footprint diversification measures bytes a crawler never sees. Premise falsified *after* drafting; the exact cost of a missing front gate. | 2026-06-01 |

## Verdict protocol

- **Four states:** `GO` (premise validated → downstream build unblocked) · `KILL`
  (premise false → don't build) · `INCONCLUSIVE` (can't confirm → resample;
  `terminal` when the premise is structurally unverifiable, e.g. G5 re-fetch
  saturation) · `BLOCKED` (Tier-2 credentials unavailable → stage parked).
- **First run per gate is a calibration pass** → `INCONCLUSIVE` by construction
  (a verdict needs a threshold, and the threshold is read off the first sample).
  Record the threshold + its rationale in the row, then rerun to reach GO/KILL.
- **No GO without a confirmed evidence sample.** Evidence cells carry aggregate
  rates / host-stripped reason counts — **never raw operator money-page URLs**
  (the no-operator-domain rule applies to `docs/ideation/`, not only
  `docs/solutions/`).

## Gate verdicts

| gate | tier | premise | verdict | rate / evidence | sample-n | date | downstream-blocked |
|---|---|---|---|---|---|---|---|
| G1 | T1 | source/host pages carrying our backlinks go noindex/blocked at a "false-success" rate | _pending_ | — | — | — | seo-indexability build-out (read from plan 002) |
| G2 | T1 | the operator's own money pages silently decay (noindex/4xx/soft-404/off-host) at a build-justifying rate | _pending — run `gate-probe --gate g2`_ | — | — | — | destination-decay machine (D1/D2) |
| G3 | T2 | any channel ever delivers a real referral session; render paths preserve `referer` | _pending (Unit 3)_ | — | — | — | GA4 referral attribution + render-path fix (Program B) |
| G4 | T2 | adult-site channel articles are surfaced/cited by AI engines (RG-kill) | _pending_ | — | — | — | GEO machine (read from plan 004) |
| G5 | T1 | footprint's pre-publish fingerprint dimensions survive into the crawled live DOM | _pending (Unit 4)_ | — | — | — | orchestrator footprint-gate (Phase 1b) |

<!-- Rows are filled by hand-curating each `gate-probe` run's JSONL verdict
     (Unit 5). G1/G4 verdicts are transcribed from plans 002/004, not machine-read. -->
