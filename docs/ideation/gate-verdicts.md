---
date: 2026-06-01
topic: gate-verdicts
type: synthesis
status: active
plan: docs/plans/2026-06-01-005-feat-gate-first-validation-and-deficit-overlay-plan.md
---

# Backlog Convergence & Decision Surface

> **Single decision surface (2026-06-02).** This file is now the authoritative
> backlog roll-up, open-work shortlist, and Phase-0 gate ledger. The planned
> `docs/ideation/SYNTHESIS.md` was intentionally not created as a separate file
> — this file fulfils that role (consol. R3: reuse the ideation ledger).
> Retired convergence docs are indexed in the "Retired docs" section below.

---

## Backlog Truth Roll-up

*Derived from `docs/plans/*.md` frontmatter. Updated 2026-06-02.*

| Status | Count | Meaning |
|---|---|---|
| **Done** | **116** | `status ∈ {completed, shipped}` — canonical done-family |
| **Parked** | **2** | `status: parked` — deliberate, each has a written resume trigger |
| **Open** | **1** | `status: active` — the genuine open set (see shortlist below) |

**Deterministic open-work query** (CRLF/BOM-tolerant, anchored):

```bash
python3 -c "
import re, pathlib
canon = {'active','completed','shipped','parked'}
for p in sorted(pathlib.Path('docs/plans').glob('*.md')):
    m = re.search(r'^status:\s*(\S+)', p.read_text(errors='replace'), re.MULTILINE)
    tok = m.group(1) if m else ''
    if tok == 'active':
        print('OPEN', p.name)
    elif tok not in canon:
        print('OFF-CANON', p.name, tok)
"
```

---

## Open-Work Shortlist

*Gate-ordered: lower gate = harder prerequisite. Execute in order.*

| Priority | Plan | Gate blocker | Action |
|---|---|---|---|
| 1 | `2026-05-25-002` channel-manifest Phase 2+3 | None (Phase 1 shipped) | `ce:work` Phase 2 (9 channels) + Phase 3 (CI gate) |

**Parked (resume triggers documented in plan frontmatter):**

| Plan | Resume trigger |
|---|---|
| `2026-05-29-006` geo-ai-citation | G4 gate returns GO |
| `2026-05-28-007` history-store→events-db | events.db corpus reaches production scale |

---

## Status Vocabulary Canon

See `AGENTS.md` → "Status vocabulary canon" for the full closed-set definition,
done-family, and maintenance rule. Quick reference:

| Token | Meaning | Done? |
|---|---|---|
| `active` | Open / executing | No |
| `completed` | All units landed | **Yes** |
| `shipped` | Landed-alias (update-on-ship discipline) | **Yes** |
| `parked` | Deferred — has resume trigger | No |

---

## Retired Convergence Docs

Prior convergence passes that are now superseded or folded:

| Doc | Status | Disposition |
|---|---|---|
| `docs/plans/2026-06-01-009-…-convergence-closeout-plan.md` | `completed` | 16 stale-active plans flipped; brainstorm triage complete |
| `docs/plans/2026-06-01-010-…-full-project-convergence-plan.md` | `parked` | Branch-landing scope deferred to merge-swarm; docs scope folded into 011 |
| `docs/plans/2026-06-01-011-…-decision-surface-plan.md` | `shipped` | This expansion (U1–U5) |
| `docs/plans/2026-05-26-002-opt-verify-consolidation-REVIEW.md` | archived | Now at `docs/_archive/plans/2026-05-26-002-opt-verify-consolidation-REVIEW.md` (E1, 2026-07-02 — the `docs/notes/` copy was a stray duplicate); findings addressed by two shipped consolidation plans |
| `SYNTHESIS.md` (planned) | not created | Role fulfilled by this file (consol. R3) |

---

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
| G1 | T1 | source/host pages carrying our backlinks go noindex/blocked at a "false-success" rate | INCONCLUSIVE (measured 2026-06-05) | detection shipped (plan 002 completed); resampled read-only on real corpus (events.db, latest-per-`live_url`): blocked **1/84 ≈ 1.2%** (one non-workhorse host, `meta_noindex`); workhorse dofollow channels all `ok` (telegra.ph n=57, blogspot n=18, x.com n=4, medium n=2); probe readable on main channels (not all-`unknown`) | 84 | 2026-06-05 | R7/R8 ledger-bridge (exclude `blocked` from `live_dofollow`) **UNJUSTIFIED at 1.2%** — net-new field+join+writeback carrying cost ≫ yield; detection + `--fail-on-unindexable` already surface it. Resample when blocked ≥5 OR a dofollow channel ≥10% |
| G2 | T1 | the operator's own money pages silently decay (noindex/4xx/soft-404/off-host) at a build-justifying rate | INCONCLUSIVE | decay 1/3=0.33 (calib, no thr); readable 3/3; lone failure=transient http_503; n=3 too small | 3 | 2026-06-01 | destination-decay machine (D1/D2) — UNJUSTIFIED at n=3 (on-demand probe suffices); resample when universe grows OR a definitive noindex/404 decay appears |
| G3 | T2 | any channel ever delivers a real referral session; render paths preserve `referer` | KILL | strip 1/2 = 0.50 (thr 0.50); preserving=work_themed; referral=absent | 2 | 2026-06-01 | Program B (GA4 referral attribution) PARKED |
| G4 | T2 | adult-site channel articles are surfaced/cited by AI engines (RG-kill) | BLOCKED | probe-citations CLI deferred (geo-ai-citation plan status:parked, U5–U8); no AI-citation tooling/creds available | — | 2026-06-02 | GEO machine PARKED (cf. geo-ai-citation plan decision); resume trigger = AI-citation corpus volume non-trivial |
| G5 | T1 | footprint's pre-publish fingerprint dimensions survive into the crawled live DOM | INCONCLUSIVE (terminal) | survival 0% terminal; readable 5/14=0.36 < 0.50 floor; rel_survived 0/5 (anchor_stripped=4, rel_rewritten=1) | 14 | 2026-06-01 | orchestrator footprint-gate (Phase 1b) — argues-against-build (premise unverifiable by re-fetch; cf. entropy-budget); terminal, do not resample |

<!-- Rows are filled by hand-curating each `gate-probe` run's JSONL verdict
     (Unit 5). G1/G4 verdicts are transcribed from plans 002/004, not machine-read. -->

## Recorded thresholds & rationale

### G3 — `strip_threshold = 0.50` → KILL (2026-06-01)

- **Measured (calibration pass):** `gate-probe --gate g3` → `strip_referer = 1/2` (0.50), `sample_n=2`.
  The two render paths through `_format_anchor_html` are `render_zh_short_article`
  (default `rel="noopener noreferrer"` → strips) and `themed_gen` main/list/work
  (`rel="noopener"` → preserves). Verified against the live call sites: there is **no** separate
  long-form `render_*` anchor path (the earlier plan note to that effect was stale).
- **Threshold rationale (0.50):** the stripping path `render_zh_short_article` is the **primary
  backlink-article renderer** (1 main + 1–2 secondary backlinks per article); the preserving path is
  the secondary themed-content one. So GA4 channel→money-page **referral attribution is structurally
  blind for the bulk of published backlinks**, regardless of any GA4/GSC setup — the static audit
  alone is decisive (no Tier-2 credentials needed).
- **Corroboration:** the owned money-page universe is tiny, so there is no referral-attribution corpus
  to begin with (operator-side signal). Two independent reasons to park Program B.
- **Scope of the KILL:** this kills the **GA4-referral-attribution build-out under the current render
  paths**. It does **not** decide the separately-deferred question "change the render path to preserve
  `referer` vs. degrade to `unattributable`". Adopting a referer-preserving `rel` on the backlink path
  would re-open G3 → rerun `gate-probe --gate g3` to recalibrate.
- **Reproduce:** `gate-probe --gate g3` then `gate-probe --gate g3 --strip-threshold 0.5`.

### G2 — money-page decay calibration → INCONCLUSIVE (2026-06-01)

- **Measured (calibration, no threshold):** `gate-probe --gate g2` → decay 1/3 (0.33), `sample_n=3`,
  all 3 readable; the single failure is a **transient `http_503`** (not a definitive noindex/4xx/soft-404).
- **Verdict rationale:** stays INCONCLUSIVE — `n=3` is below any meaningful sample floor and the lone
  "decay" is a transient server error. Forcing GO/KILL on this calibration run would violate the
  "partial/transient sample ≠ confident verdict" discipline (consol. R11).
- **Build implication:** the destination-decay **machine** (persist receipts to an events.db KIND +
  LedgerRow field + trend; former D1/D2) is **not justified at this scale** — the zero-cost on-demand
  `gate-probe --gate g2` already covers a 3-URL owned universe. **Resample trigger:** the owned money-page
  universe grows materially, **or** a definitive (noindex/404/soft-404/off-host) decay appears.
- **Operational note (act now, separate from the gate):** one money page is currently returning
  `http_503` — worth a manual check; backlinks pointing at it yield nothing while it is down.

### G5 — footprint survival → INCONCLUSIVE-unmeasurable (terminal, 2026-06-01)

- **Measured (calibration):** `gate-probe --gate g5` → re-fetch readable **5/14 (0.36) < 0.50 saturation
  floor** → **terminal** INCONCLUSIVE-`unmeasurable`. Among the 5 readable, `rel_survived=0`
  (`anchor_stripped=4`, `rel_rewritten=1`); failure reasons network_error=6, unreachable=2, invalid_url=1.
  (events.db is test-data-dominated; only a few links are real channels.)
- **Verdict rationale:** the footprint-gate premise — *do pre-publish fingerprint dimensions survive into
  the crawled live DOM?* — is **unverifiable by canary re-fetch**: most published-page hosts are
  anti-bot / unreachable to the verifier UA. Terminal (do **not** resample) by the saturation-floor protocol.
- **Build implication:** an unmeasurable premise **argues against building** the orchestrator
  footprint-gate (Phase 1b) — the same conclusion entropy-budget reached, by a different route. The signal
  that *did* come through (`rel_survived=0/5`) points the same way. Treat Phase-1b footprint-gate as parked.

### G1 — source-page indexability → INCONCLUSIVE (2026-06-02)

- **State:** the detection shipped — plan `2026-06-01-002-source-indexability-detection` is `completed`
  (`recheck/indexability.py` adds `indexability ∈ ok|blocked|unknown` as orthogonal metadata on the
  recheck probe, never changing the liveness verdict).
- **Why INCONCLUSIVE (not run here):** producing the verdict requires a live `recheck-backlinks` pass
  over a **real published corpus** — which **writes `link.rechecked` events to events.db** (not a pure
  read-only probe like `gate-probe`). Mutating events.db while the recheck→deficit-overlay→re-plan loop
  is live is a side effect not worth triggering for a gate calibration. At the current corpus (the same
  test-data-dominated, ~5/14-readable set G5 saw) the `unknown` rate would be near-total → unmeasurable,
  which plan 002's own Phase-0 GO/NO-GO criterion already flags as "do not build yet."
- **Resample trigger:** a non-test published corpus of real channel pages exists; then run
  `BACKLINK_PUBLISHER_CONFIG_DIR=<prod> recheck-backlinks …` and read the `blocked` / `unknown` rates.
- **Resample (2026-06-05) — now measured:** the real corpus matured (51acgs-target rechecks over
  telegra.ph / blogspot / x.com / medium / github.io / livejournal). Read-only scan of `events.db`
  `link.rechecked` (latest-per-`live_url`, n=84): **blocked 1/84 ≈ 1.2%** — a single `meta_noindex`
  page on a non-workhorse host; the workhorse dofollow channels are all `ok` (telegra.ph 57, blogspot 18,
  x.com 4, medium 2). The probe **reads** the main channels (only a few `unknown`), so the low rate is a
  real measurement, not an all-`unknown` blind spot.
- **Build implication (mirrors G2):** the **R7/R8 ledger-bridge** — a net-new `LinkRecord.indexability`
  field + a `build_target_buckets` join (or history-store writeback) so `equity-ledger` excludes
  `blocked` from `live_dofollow` — is **UNJUSTIFIED at 1.2%**: its carrying cost dwarfs the yield of
  correctly discounting one link, and the operator already sees that link via the shipped detection
  (`_indexability_summary`, `_alive_blocked_count`) and the opt-in `--fail-on-unindexable` gate (exit 6).
  Detection-first was the right call; the equity-loop stays deferred. **Resample trigger:** `alive`-but-
  `blocked` real links reach ≥5, **or** any single dofollow channel's blocked rate reaches ≥10%.

### G4 — GEO / AI-citation → BLOCKED (2026-06-02)

- **State:** the `probe-citations` CLI that would emit G4's verdict is **deferred** — the
  `2026-05-29-006-geo-ai-citation-closed-loop` plan is `status: parked` (U1–U4 shipped #331; U5–U8
  deferred behind an internal credit-gate → `probe-citations` dependency).
- **Why BLOCKED (not INCONCLUSIVE):** G4 is Tier-2 and its probe tooling/credentials do not exist yet, so
  per the four-state protocol the gate is `BLOCKED` (parked), not a resample-able INCONCLUSIVE. The GEO
  machine stays parked — this transcribes the geo plan's *existing* PARK decision, it is not a new kill.
- **Resume trigger (from the geo plan):** backlink/AI-citation corpus volume becomes non-trivial
  (attribution has no signal at current owned-target volume). Resumes at the geo plan, not a re-brainstorm.

### Probe — reliability policy enforce path (live verification) → GO (2026-06-03)

- **Nature:** a pure-verification probe (R16-exempt — not a Phase 1–N build gate, no `gate-probe` run).
  Plan `docs/plans/2026-06-03-007-feat-live-verify-reliability-policy-plan.md`; tests
  `tests/test_reliability_policy_live.py` (12 cases, all green; existing reliability suite unaffected).
- **What GO certifies (scoped):** with `BACKLINK_PUBLISHER_RELIABILITY_POLICY_ENABLED=1`, the **CLI
  call-site branch selection** routes dispatch through `publish_with_policy` (not direct
  `adapter_publish`) at **both** seams — `_engine.py` (`run_publish_loop`) and `_resume.py`
  (`_publish_one_resume_item`) — with flag-off passthrough intact. Stub-level policy behaviors verified
  end-to-end on the non-browser-tier `fake` platform: health gate `skipped_policy` (browser-tier `velog`),
  circuit OPEN → `skipped_circuit_open` (pre-seeded `circuit.trip`), recovery (cooldown→HALF_OPEN allows
  through), and `publish_attempt` `success` / `external_error` observability events.
- **Explicitly NOT covered (out of scope):** real-platform error-mapping fidelity (real
  429/503/ban/session-expiry → typed exception vs generic `Exception`→`TRANSIENT`-no-trip) — needs a bound
  channel + credentials. And HALF_OPEN **trial-count limiting**: `circuit._increment_half_open_try` has
  **no caller on the publish path** (`is_tripped` allows traffic in HALF_OPEN without consuming a trial) —
  surfaced as a **potential production gap for a separate fix plan**, not retired here.
