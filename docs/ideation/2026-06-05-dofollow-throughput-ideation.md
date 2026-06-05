---
date: 2026-06-05
topic: dofollow-throughput
focus: business bottleneck — throughput of actually-working (live, un-stripped) dofollow backlinks
---

# Ideation: Dofollow-Throughput (focused generative pass)

> **Focus.** Not the converged idea-backlog (see `2026-06-05-backlog-convergence-ideation.md`),
> but a fresh generative pass aimed squarely at the *one* business bottleneck:
> **how many published links actually survive as live dofollow** (deep pages strip
> 56-67%, telegraph ≈86% of all strips, only ~73 verified live-dofollow on 1 owned
> site, non-author path never run). 4 ideation agents × frames generated 32 raw
> candidates; 1 adversarial agent attacked the merged 14 against shipped code +
> the active plan 008 R-trace + the gate ledger.

## Headline finding (read this first)

**The dofollow-throughput bottleneck is almost entirely already *owned* — by shipped
code and by the active-but-unshipped plan 008 (`core-upgrade-prove-and-prune`).
The lever is *executing* that plan, not generating new ideas.** Adversarial audit
verdict on the 14 merged candidates:

- **Already shipped** (the repo's #1 trap): auto-republish-on-strip closed loop
  (`gap/engine.py:226` `plan_keepalive_gap`); example.com provenance exclusion
  (`gap/engine.py:200`, `keep_alive.py:24`, `scorecard/links.py:40`); per-target
  strip_rate (`keep_alive.py:68`); optimizer R1 collector merged to main (`a7f3f7c`).
- **Verbatim plan 008 units (swarm-collision risk, do NOT re-ideate):** strip-penalty
  dispatch optimizer + `min_weight` floor = **R3**; non-author publish live-fire = **R7/R8**;
  "retire telegraph" = a *subset* of R3 **and** the exact routing-drop anti-pattern R3
  is built to prevent.
- **Thin / missing data:** depth-aware routing & pre-flight strip predictor rest on a
  *single* memory note (56-67%) with no sampled n; a daily survivor digest emits noise
  on an immature ~73-link cohort (most links <30d old).

After that filter, **only 1 idea is a clean, verified, non-colliding, high-leverage
KEEP** (#1 below). Two more are defensible but smaller/deferred. This is an honest
"<5 survivors" result, not a padded list.

## Latent P0 surfaced during audit (flag, don't fix here)

`optimization/rules.py:207` `_rule_aggregated_stats` **exists and is enabled by default
but has NO `min_weight` floor** (the "already at minimum" branch at lines 269-276 is
dead — nothing clamps), and it is **absent from `default_state()`** (`models.py:80`).
Net: a floorless strip-penalty rule can multiply a channel's weight toward 0. Telegraph
is 86% of strips **and** a main-volume channel — floorless penalty can collapse publish
volume. This is exactly the P0 documented in memory `project-core-upgrade-prove-and-prune-plan008`.
**Owned by plan 008 R3** — surfaced here so it isn't lost; the fix is to land R3, not a new idea.

## Codebase Context

- 24 registered platforms: **11 `dofollow="uncertain"`**, 8 False, 5 True
  (`publishing/adapters/__init__.py` / `registry.registered_platforms()`). A channel is
  only "confirmed" after an **OUR-pipeline** canary, never a 3rd-party probe
  (`docs/solutions/dofollow-platform-shortlist.md`).
- Liveness engine shipped: `recheck/probe.py` 5-verdict taxonomy
  (alive / host_gone / link_stripped / dofollow_lost / probe_error), per-link events in
  `events.db`. Survival scorecard renders in `health.html`; per-link drawer shipped (plan 009).
- Throttle enforced **Medium-only**; 22 of 24 platforms carry `throttle_band=None`
  (most deliberately — "no documented limit").
- Empirical corpus is small and single-path: ~73 verified live-dofollow, 1 owned target,
  author path only (`events.db` otherwise dominated by example.com test data).

## Ranked Ideas

### 1. One-command OUR-pipeline dofollow canary sweep for the 11 "uncertain" platforms
**Description:** A single CLI/job that publishes one disposable-but-real canary through
**our own pipeline** to each of the 11 `dofollow="uncertain"` adapters (wordpresscom,
hashnode, writeas, substack, rentry, txtfyi, notesio, hatena, hackmd, mataroa,
gitlabpages), rechecks each via `probe.py`, and bulk-flips the registry taxonomy
`uncertain → confirmed_dofollow | nofollow` from the real verdict. Can run on the
**author path that already works today** — does not require the non-author path.
**Rationale:** 11 of 24 platforms (≈46% of the universe) are dispatch-weighted on a
*guess*. Plan 008 **explicitly leaves this on the table** (plan line 45: "this iteration
does not flip 'uncertain' platforms"). Resolving even half permanently widens the
known-good dofollow funnel that every future plan + the R3 optimizer routes into — pure
compounding, zero collision with active work.
**Downsides:** Each confirmation needs a real publish + a settle-window recheck (not
instant); a few platforms may confirm as nofollow and get pruned (still a win — removes
guesswork). Needs disposable canary content that won't pollute the real scorecard
(provenance exclusion already exists to lean on).
**Confidence:** 85%
**Complexity:** Medium (needs `ce:plan`; R16-exempt — reuses shipped adapters + probe + canary infra)
**Status:** Explored — brainstorm started 2026-06-05

### 2. Throttle-band enforcement — narrowed to platforms with a *real* documented limit
**Description:** Generalize the Medium-only throttle into a band-driven pre-publish pacer
keyed on (platform, account), but **only** populate/enforce bands where a genuine
documented rate limit exists — not blanket-applied to the 22 `None` platforms (most have
no limit and would just be slowed for nothing).
**Rationale:** A rate-limited or banned account zeroes out a whole confirmed-retainer
channel permanently — the most expensive form of lost throughput. This is reliability
insurance that protects the compounding pool, **but it does not by itself raise surviving
dofollow** — hence #2, not #1.
**Downsides:** Determining "real limit vs none" is per-platform research; over-applying
adds latency for no gain. Value is insurance, not direct yield.
**Confidence:** 70%
**Complexity:** Low-Medium
**Status:** Unexplored

### 3. `probe_error` retry-lane isolation (deferred until the corpus grows)
**Description:** `probe_error` (5xx/403/429/timeout/ssrf) correctly does not advance the
recheck cursor; at scale a platform having a bad day grows a perpetually-retried backlog
that crowds out fresh rechecks. Add a separate per-platform error-rate-aware retry lane.
**Rationale:** Recheck throughput is itself a future bottleneck — stale verification means
you can't trust which links are live. Non-overlapping with plan 008.
**Downsides:** **Premature now** — corpus is ~73 links and `_BATCH_BUDGET_S=600` already
prevents starvation at this size. Only bites after plan 008 R4 widens recheck cadence and
volume climbs. Defer behind R4.
**Confidence:** 60%
**Complexity:** Low-Medium
**Status:** Unexplored → **deferred**

## Rejection Summary

| # | Idea | Verdict | Reason |
|---|------|---------|--------|
| 1 | Strip-penalty dispatch optimizer + min_weight floor | KILL | Verbatim plan 008 **R3**; rule exists `rules.py:207`, only floor missing — execute, don't re-ideate |
| 2 | Run never-run non-author publish path | KILL | Verbatim plan 008 **R7/R8**; seam-locked publish path = highest collision cost |
| 3 | Retire telegraph from default dispatch | KILL | Subset of R3 **and** the routing-drop anti-pattern R3 prevents (telegraph is main-volume) |
| 4 | Auto-reroute/replenish on strip (closed loop) | KILL (shipped) | `gap/engine.py:226` `plan_keepalive_gap` already republishes to sticky retainer on strip |
| 5 | events.db provenance / example.com filter | KILL (shipped) | `gap/engine.py:200`, `keep_alive.py:24`, `scorecard/links.py:40` already exclude it |
| 6 | Strip-rate rollup + auto-quarantine | DEMOTE | per-target strip_rate built; per-platform/depth view marginal; auto-quarantine = R3 collision |
| 7 | Depth-aware routing (avoid 56-67% deep strip) | DEMOTE | "56-67%" is one memory note, not a sampled rate; resample before auto-routing on it |
| 8 | Daily net-survivor-delta digest | DEMOTE | Overlaps R5 dashboard; morale ≠ throughput; immature cohort → noise |
| 9 | Identity rotation pool as dispatch dimension | DEMOTE | No identity dim in `route()`; net-new arch; zero data pre-R7 |
| 10 | Catalog probe→YAML→canary auto-onboarding | DEMOTE | Straddles active plan 005 + channel-manifest (`gate-verdicts.md:53`) |
| 11 | Survival-gated / pre-flight strip predictor | DEMOTE | Needs a survival corpus that doesn't exist yet (n<2/platform); wrong-but-green risk |
| — | footprint / GA4 / GEO / decay-monitor | KILL | gate-killed (G5/G3/G4/G2) — not revived |

## Stale-memory corrections surfaced (verify + update)

Code audit contradicts/updates standing notes — flag for memory hygiene:
- **Keepalive republish-on-strip loop is SHIPPED** (`gap/engine.py:226`) — any "links die
  silently, no reaction" framing is stale.
- **example.com contamination is already filtered** in gap/scorecard paths — not an open gap.
- **Optimizer R1 (collector) is merged to `main`** (`a7f3f7c`); R3 floor is the live gap
  (and the latent floorless-rule P0 above).
- Only **2 of 24** platforms have a throttle_band — confirms the enforcement gap premise,
  but most `None`s are intentional.

## Session Log
- 2026-06-05: Focused generative pass on the dofollow-throughput bottleneck (user chose
  "聚焦業務瓶頸生成" over fresh-open or continue-convergence). 2 grounding agents +
  4 framed ideation agents (32 raw → 14 merged/synthesized) + 1 adversarial agent
  (audited each vs shipped code, plan 008 R2-R10 trace, gate ledger). Honest result:
  most candidates already shipped or are verbatim plan-008 units; **1 clean high-leverage
  survivor (#1 canary sweep of 11 uncertain platforms)**, 2 smaller/deferred. Net steer:
  the throughput lever is executing plan 008 R2-R10, not new ideation.
- 2026-06-05 (cont.): User selected **#1 (canary sweep)** for brainstorming. Marked
  Explored; handing off to `ce:brainstorm` with #1 as the seed.
