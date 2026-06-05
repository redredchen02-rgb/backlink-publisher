---
date: 2026-06-05
topic: backlog-convergence
focus: converge existing backlog (no new ideas) — surface executable, low-blocker, high-leverage work
---

# Ideation: Backlog Convergence (Round 13 — converge, not generate)

> **Why this is a convergence pass, not a 13th fresh-pass.** The repo already
> holds 16 ideation docs (round1→round12), 83 brainstorms, and — after
> archiving the last open plan (`2026-05-25-002` channel-manifest, now in
> `docs/_archive/plans/`) — **0 active plans**. Project memory's standing signal:
> *the bottleneck is execution, not ideas* (`backlog-bottleneck-is-execution`).
> So this pass scans the existing corpus + code for already-vetted, un-executed,
> non-gate-killed work instead of generating new candidates.

## Codebase Context

- **Backlog truth (per `gate-verdicts.md` roll-up + today's audit):** 116 done,
  2 parked (resume-triggered), 0 genuinely open. The idea backlog is ~99% converged.
- **Gate ledger kills/parks** (do not revive): G3 KILL (GA4 referral attribution),
  G4 BLOCKED (GEO/AI-citation), G1/G2 INCONCLUSIVE-parked (seo-indexability,
  destination-decay), G5 KILL terminal + entropy-budget KILLED (footprint
  diversification — operator `<a>` bytes never reach the crawled DOM).
- **Real bottleneck confirmed by code audit:** canonical CI (`PYTHONHASHSEED=0`
  full suite) is RED — 12 failed / 10025 passed. Remaining work is execution
  (red-test repair, dead-capability wiring, silent-drop closers), not ideation.

## Ranked Ideas

### 1. Fix the 12 red tests at `PYTHONHASHSEED=0`
**Description:** Canonical CI is red (12 fail / 10025 pass; memory baseline was 11
— drift up). Cluster: `test_pipeline_api_seam` (keepalive_job.py:361 uses raw
`subprocess.run` for a pipeline publish, banned by seam allowlist),
`test_no_complexity_regrowth[test_webui_route_contract.py]` (over CC ceiling),
`reliability_policy_live` r5 events ×2, plus a set that passes in isolation but
fails in-suite (test-ordering pollution — hunt with `-p no:randomly`).
**Rationale:** A red canonical CI blocks every clean ship — the literal execution
bottleneck. Highest leverage by far.
**Downsides:** Pollution hunt is the slow part; each fix is otherwise small.
**Confidence:** 95% (failures reproduced twice in code audit)
**Complexity:** Medium
**Status:** Unexplored → **selected for execution 2026-06-05**

### 2. Config-driven lightweight adapters (YAML catalog + `verify-dofollow` CLI)
**Description:** Add anonymous/API-key dofollow platforms by dropping a `.yaml`
into a catalog dir (no Python), plus a verify-dofollow CLI and Tier-1
(`--dofollow-only`) dispatch flag. Reuses `http_form_post.py` + registry +
`_nofollow_rationales` contract.
**Rationale:** Collapses "find new dofollow platform → days to wire an adapter"
into "add one YAML" — directly attacks channel/backlink throughput, the real
business bottleneck.
**Downsides:** New surface to keep in sync with the registry/schema; needs a plan.
**Confidence:** 80% **Complexity:** Medium (needs `ce:plan`)
**Status:** Unexplored
**Source:** `docs/brainstorms/2026-06-05-config-driven-lightweight-adapters-requirements.md`
(no plan yet; R16-exempt — reuses existing adapters, no new Phase-machine premise)

### 3. Run Inbox — `bp runs` + `resume` CLI
**Description:** Checkpoint/resume logic ships but has NO console entrypoint in
`pyproject.toml`, so the capability is dead-in-practice. Add `bp runs` (list
resumable runs + status + exact resume command) and a `resume` script.
**Rationale:** Revives an already-built but unreachable capability — high value,
low cost, gate-clean.
**Downsides:** Minor — needs a stable run-receipt format.
**Confidence:** 82% **Complexity:** Low-Medium
**Source:** ideation R11 #3 (verified: no `runs`/`resume` script in pyproject)
**Status:** Unexplored

### 4. Reconcile-swallow recovery log (int counter → event kind)
**Description:** UNIQUE-collision republish drops are recorded only as an int
(`skipped_due_to_dedup` in `_project_reducers.py`). Emit a `reconcile_swallowed`
event kind instead so the equity ledger stays honest.
**Rationale:** Closes a silent data-drop; complements the just-shipped equity
ledger work.
**Downsides:** Touches the events reducer — needs care with determinism tests.
**Confidence:** 78% **Complexity:** Low-Medium
**Source:** ideation R9 #2 (verified still an int counter)
**Status:** Unexplored

### 5. Safety/config quick-win bundle (one PR)
**Description:** (a) Consolidate the two near-identical circuit trip-threshold env
vars (`...CIRCUIT_CONSECUTIVE_ERRORS` in circuit.py:155 vs
`...CIRCUIT_ERROR_THRESHOLD` in reliability/policy.py:65) to prevent operator
misconfig; (b) one-time chmod 0600 migration for pre-#140 `llm-settings.json`
(api-key file may be 0644 on legacy installs); (c) replace hardcoded anchor
`_MIN_KO_HANGUL_RATIO=0.30` magic number (recurred 3 ideation rounds untouched)
with a calibrated per-language constant + diagnostic.
**Rationale:** Three confirmed S-effort hardening closers, gate-free.
**Confidence:** 85% **Complexity:** Low (each S)
**Source:** residual audit (#5/#7) + ideation R9 #5 / R8 #15
**Status:** Unexplored

## Rejection Summary

| # | Idea | Reason Rejected |
|---|------|-----------------|
| 1 | footprint partition / emit-side / cross-adapter (R8#4, R9#4, R12#6) | G5 KILL terminal — footprint bytes never survive into crawled DOM |
| 2 | destination-decay monitor (R12#4) | G2 parked — n=3 insufficient; on-demand probe suffices |
| 3 | GA4 referral attribution | G3 KILL — channels strip referer |
| 4 | GEO / AI-citation machine | G4 BLOCKED — no citation tooling/creds |
| 5 | canary stale-detection no-op fix (canary_targets.py:60) | Real bug but M-effort, single-point impact — honorable mention, not top 5 |
| 6 | link-kind × dofollow cross-tab (R9#3/R8#5) | Lower confidence (62-70%); read-side nice-to-have |
| 7 | collapse `*-login` CLIs (R8#6) | UX/DRY only, low confidence |
| 8 | Medium multi-candidate selectors (R14#6) | High confidence but oldest doc — DOM may have shifted, needs re-grounding |
| 9 | ~76 other brainstorms | Already have a completed/archived plan (shipped, different vocabulary) |

## Stale-memory corrections surfaced (verify + update)

Code audit contradicts four memory notes — flagged for correction:
- `net_safety.py` is NOT dead code (8+ importers; live SSRF guard) — contradicts `adapter-dedup-is-intentional-divergence`
- Azure wireserver 168.63.129.16 IS in the blocklist (net_safety.py:27) — `ssrf-live-blocklist-azure-gap` likely resolved
- `settings.html` now has only 2 hardcoded hex (R10 residual cleared) — contradicts `webui-ux-overhaul-shipped-r10-residual`
- HALF_OPEN circuit trial-limiter dead code already removed — contradicts `reliability-policy-circuit-facts`

## Session Log
- 2026-06-05: Convergence pass (round 13). User chose "converge backlog" over generating. 3 parallel mining agents scanned 83 brainstorms + 16 ideation docs + code residuals against the gate-kill ledger. ~99% converged; 5 survivors (execution-weighted). User selected #1 (red-test repair) for immediate execution; artifact written before handoff.
- 2026-06-05 (cont.): **#1 aborted on collision** — a live agent/swarm was actively repairing the SAME red tests in the shared canonical tree (24+ uncommitted files; `test_pipeline_api_seam.py` re-edited 1 min into my work; new brainstorms appearing). My planned seam fix was already made by them (identical approach). Per memory `never-mutate-shared-worktrees` / `tmp-clone-not-safe-from-live-agent`, stopped all code work — even isolated clones are unsafe vs a live force-pushing swarm. Only zero-collision new-file artifacts are safe right now.
- 2026-06-05 (cont.): Pivoted to collision-free planning. Wrote **plan 2026-06-05-005** (idea #2, config-driven adapters) and **plan 2026-06-05-006** (idea #5 hardening bundle), both with explicit "build-after-tree-settles" sequencing + hot-file maps + `claims:{}` opt-out. (Originally numbered 003/004; renumbered to 005/006 after the live swarm created its own 2026-06-05-003 AI-engine plan mid-session — plan_id collision avoidance.)
- 2026-06-05 (cont.): **Idea #3 (Run Inbox) RETRACTED — already shipped.** Verify-before-planning caught the mining agent's stale claim: `publish-backlinks --list-runs` + `--resume` exist, `checkpoint.list_incomplete()`/`list_all_runs()` exist, WebUI `/checkpoint/resume` + `/checkpoint/dismiss` routes exist. The "no console entrypoint" claim was technically-true-but-misleading (no separate `runs` script, but capability fully reachable). No greenfield plan written — residual is cosmetic at most (dedicated `/runs` page vs existing resume banner). Classic `plans-marked-active-may-be-already-shipped` trap.
