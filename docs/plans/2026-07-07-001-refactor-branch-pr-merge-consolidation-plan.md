---
title: "chore: Branch & PR Merge Consolidation — Round 4"
type: refactor
status: completed
date: 2026-07-07
claims: {}  # pure git/PR housekeeping — no new application logic authored by this plan itself; W10/W13 feature code was already authored on their own branches under plan 2026-07-06-005
---

# chore: Branch & PR Merge Consolidation — Round 4

## Overview

Bring the `backlink-publisher` workspace back to a clean, mergeable state: sync local `main`, land the two genuinely outstanding SPA units (W10, W13) via one PR, prune the branches/worktrees confirmed already-merged or content-stale, and refresh `AGENTS.md`'s branch documentation. This is the fourth round of this recurring task.

Three prior rounds already ran: `docs/plans/2026-07-02-002-chore-branch-pr-consolidation-plan.md` (local branch/worktree consolidation), `docs/plans/2026-07-06-006-opt-master-convergence-optimization-plan.md` (fleet-preview unfreeze + convergence), and `docs/plans/2026-07-06-007-refactor-branch-pr-merge-consolidation-plan.md` (Round 3 — merged 6 PRs, pruned 13 branches). None left the workspace in a permanently steady state — this is expected for a workspace with sustained concurrent-session activity, not a sign any prior round failed. This round's starting state is markedly cleaner than Round 3's: local `main` is only 1 commit behind `origin/main` (no unpushed local work), and 7 more PRs (#77–#83) merged between Round 3's closeout and now, absorbing all but 2 of the W-numbered units Round 3 had explicitly left as "presumed concurrent WIP."

**Live-state findings (2026-07-07), superseding this document's own snapshot the moment execution re-verifies otherwise:** of the 24 non-`main` branches/worktrees present, live ancestry checks (`git merge-base --is-ancestor <branch> origin/main`) show 19 already merged into `origin/main` (18 prunable now; `feat/w8-spa-shell-upgrade` excluded — see below). Of the remaining 5, content-diff investigation (not just ahead/behind commit counts) found: only `feat/w10-cross-page-deeplink` and `feat/w13-mutation-error-reporting` carry genuinely unlanded work — and `feat/w10` already contains `feat/w13`'s sole commit as its own parent, so one PR covers both. The other 2 apparent-ahead branches (`docs/u4-test-measurement`, `fix/main-mypy-breakage`) are fully stale: their distinguishing content — a CC-30 complexity-backstop test, a `docs/solutions/` measurement doc, and mypy fixes matching already-merged PR #83's title — was independently verified present on `origin/main` already. The last one, `integration/2026-07-06-005-w1-w2-w4-w5-w6-w10-w12-w13-w14-w15`, is redundant with `feat/w10-cross-page-deeplink` (same 2 real commits plus one no-op merge of already-landed `chore/w14-blueprint-audit` content) — but because it's a distinct commit object, a plain ancestor-check will never confirm it merged even after Unit 2 lands; it needs the same content-verification method as the other 2 stale branches, not `git merge-base --is-ancestor`. One worktree, `bp-w8-shell` (`feat/w8-spa-shell-upgrade`), has live uncommitted edits (`Icon.vue`, `SideNav.vue`, `TopBar.vue`, `navItems.ts`) even though its branch is already fully merged — signaling another session is still actively using that worktree; it is left completely untouched throughout. (This document's review pass also caught that its own first-pass research had silently dropped `integration/w8-w11-w15-frontend` — a 19th already-merged branch — from Unit 5's candidate list; folded back in below.)

## Problem Frame

User request: "幫我MERGE分支" (help me merge branches) — the same recurring request as all 3 prior rounds, worded slightly more tersely this time (no explicit "and PRs"). Per established precedent (see prior rounds' own scope-boundary notes), this plan interprets it with the same broader scope: merging what's mergeable, pruning what's already landed, and leaving genuinely active concurrent work untouched — not just the two words taken literally.

Investigation found the actual remaining work is much smaller than Round 3's: no PRs are currently open, `main` needs only a fast-forward pull (no push required), and of the branches Round 3 deliberately left untouched as presumed-WIP, all but 2 have since been absorbed into `main` via other sessions' own PRs. The two real survivors are the W10 (cross-page History↔error-report deep-link) and W13 (mutation error-report coverage for History/Drafts/Settings) units from `docs/plans/2026-07-06-005-opt-webui-uiux-comprehensive-plan.md`.

## Requirements Trace

- R1. The two genuinely outstanding SPA units (W10, W13) reach `main` via one reviewed, green PR.
- R2. Every branch/worktree treated as "already merged" is confirmed via a live ancestry check at execution time, not assumed from this document's snapshot.
- R3. `docs/u4-test-measurement` and `fix/main-mypy-breakage` are each re-confirmed content-stale (their distinguishing content verified present on `origin/main`) before deletion — never deleted on ahead-count alone.
- R4. Every branch/worktree deletion gets an `archive/<branch-name>` tag, pushed to `origin`, before the branch itself is removed (continuing the convention from Rounds 2/3).
- R5. Any branch or worktree showing live uncommitted edits, or other evidence of recent concurrent activity, is left completely untouched.
- R6. Local `main` is synced to `origin/main` without losing or duplicating history.
- R7. `AGENTS.md`'s branch/worktree documentation section is refreshed to reflect the post-consolidation state.
- R8. Each unit re-verifies live git/PR/worktree state immediately before acting, rather than trusting this document's tables — this workspace has a confirmed, repeated history of concurrent-session state shifting mid-plan (see prior rounds and [[project_shared_directory_hazard]]).
- R9. If re-verification under R8 shows a unit's target no longer matches this document's description, the unit pauses and the discrepancy is documented inline rather than executed against a stale assumption.

## Scope Boundaries

- No new application features or bug fixes beyond what's needed to make the W10/W13 PR mergeable (conflict resolution only, additive-first).
- No `gitlab` remote work (out of scope since Round 3; unchanged).
- `feat/w8-spa-shell-upgrade` / `bp-w8-shell` worktree: explicitly out of scope for the entire plan, left byte-for-byte as found, regardless of the branch itself already being an ancestor of `origin/main`.
- `bp-baseline-preref`: already resolved by Round 3's 2026-07-07 addendum (diff snapshot taken, scratch changes discarded, worktree kept as a baseline reference). Not revisited here.
- This plan's broader-than-literal scope (merge 1 PR, prune ~23 branches, refresh `AGENTS.md`) mirrors all 3 prior rounds' established practice for this identical recurring request.

### Deferred to Separate Tasks

- Whatever session owns `bp-w8-shell`'s live edits — its own follow-up, entirely outside this plan.
- Any further W-numbered units from `docs/plans/2026-07-06-005-opt-webui-uiux-comprehensive-plan.md` not yet started as of execution time.
- Restoring `gitlab` push access.

## Context & Research

### Relevant Code and Patterns

- `AGENTS.md:311-318` — branch/worktree documentation, last refreshed by Round 3; stale again as of this plan's research and refreshed by this plan's Unit 6.
- `AGENTS.md:450` — `scripts/prune-stale-worktrees.sh --dry-run`, the sanctioned worktree-cleanup mechanism.
- `docs/plans/2026-07-06-005-opt-webui-uiux-comprehensive-plan.md` — source plan for W10/W13 and every other W-numbered unit referenced throughout this document.
- `monolith_budget.toml` / `complexity_budget.toml` — re-measure after the W10/W13 merge; both files have shifted in every recent merge round.

### Institutional Learnings

- `docs/solutions/workflow-issues/verify-repo-state-before-planning-2026-05-18.md` and `multi-agent-turf-check-before-claiming-work-2026-05-20.md` — re-verify PR/branch/worktree state live immediately before acting; this plan's own research already caught state that AGENTS.md's Round-3-era documentation had recorded as "presumed active WIP" but which had since fully landed.
- `docs/solutions/workflow-issues/scan-parallel-prs-before-blocker-2026-05-18.md` — relevant precedent for confirming `feat/w10-cross-page-deeplink` supersedes `feat/w13-mutation-error-reporting` before opening any PR for the latter.
- `docs/solutions/workflow-issues/push-early-committed-survives-branch-deletion-2026-05-27.md` — informs pushing the W10/W13 merge and all archive tags promptly.
- `docs/solutions/workflow-issues/foreign-agent-wip-spreads-across-worktrees-2026-05-20.md` and `external-agent-edits-in-shared-worktree-2026-05-18.md` — directly govern the `bp-w8-shell` exclusion (R5).
- `docs/solutions/test-failures/post-fleet-merge-full-suite-measurement-2026-07-06.md` — confirmed present on `origin/main`; its existence there is itself part of this plan's evidence that `docs/u4-test-measurement` is stale (R3).

## Key Technical Decisions

- **Merge via `feat/w10-cross-page-deeplink`, not `integration/2026-07-06-005-w1-w2-w4-w5-w6-w10-w12-w13-w14-w15`**: both contain the identical W10+W13 commits; the integration branch adds only a redundant merge of already-landed `chore/w14-blueprint-audit` content. The feat branch is the more direct, cleaner PR source.
- **No separate PR for `feat/w13-mutation-error-reporting`**: its sole commit (`a8811362`) is the parent commit of `feat/w10-cross-page-deeplink` — merging W10 merges W13 automatically. The branch is pruned in Unit 5, not merged independently.
- **`docs/u4-test-measurement` and `fix/main-mypy-breakage` classified stale by content verification, not ahead-count**: both showed as "ahead" of `origin/main` by raw commit count, but their distinguishing content (CC-30 backstop test, post-fleet-merge measurement doc, mypy fixes matching PR #83's own title) was independently confirmed already present on `origin/main` — satisfying R3 rather than assuming staleness from the ahead/behind numbers alone.
- **`bp-w8-shell` excluded from all units, not just the prune step**: its live uncommitted edits are the only concrete evidence of ongoing concurrent activity found this round; treated as fully out of scope per R5, matching every prior round's identical precedent for such worktrees.
- **Archive-tag before every deletion (R4), pushed to `origin`**: continuing the convention established in Rounds 2/3, applied here to all ~23 pruned branches (including `feat/w10-cross-page-deeplink` itself once its PR merges, and `integration/2026-07-06-005-...` once content-verified redundant).

## Implementation Units

- [x] **Unit 1: Sync local `main` with `origin/main`**

**Goal:** bring local `main` current before any merge or prune work begins.

**Requirements:** R6, R8

**Dependencies:** None

**Files:** none (git operation only)

**Approach:** `git fetch`; re-verify local `main` still has 0 unique commits ahead of `origin/main` (confirmed 0 ahead / 1 behind at planning time — re-check live, since this can shift); fast-forward pull.

**Test scenarios:** Test expectation: none -- pure git sync, no code change.

**Verification:** local `main`'s tip matches `origin/main`'s tip; `git status` clean.

- [x] **Unit 2: Review and merge the W10/W13 SPA units via `feat/w10-cross-page-deeplink`** — **major rescope during execution.** Opened PR #84, then found (via a live 3-way merge attempt, not just `merge-tree`) 6 real conflicting files. Investigation revealed `origin/main` already carries a *separately-authored, more mature* implementation of W10 and most of W13 (via `integration/w4-w5-w10-w13-reintegrate-u5`, confirmed an ancestor of `origin/main`) — `rowReportLinks.ts`, `HistoryPage.vue`'s deep-link wiring, and `DraftsPage.vue`'s `useMutation` migration were all already shipped and integrated with unrelated later work (e.g. U5's pagination-aware refetch, which `feat/w10-cross-page-deeplink`'s copy predates — merging it would have been a regression). Only Settings-card mutation error-reporting (`useSettingsForm.ts` + 5 callers) was genuinely missing. Closed PR #84 unmerged with an explanation; hand-ported just the Settings files into a fresh branch (`feat/w13-settings-mutation-error-reporting`); full suite green (484/484 vitest, typecheck, eslint, build); opened and merged PR #85. Archive-tagged and pruned `feat/w10-cross-page-deeplink`, `feat/w13-mutation-error-reporting`, `integration/2026-07-06-005-w1-w2-w4-w5-w6-w10-w12-w13-w14-w15` (redundant with the same content), and PR #85's own source branch.

**Goal:** land the two genuinely outstanding units from plan `2026-07-06-005` — cross-page deep-linking between History rows and error-reports (W10), and mutation error-report coverage for History/Drafts/Settings (W13).

**Requirements:** R1, R8, R9

**Dependencies:** Unit 1

**Files:**
- Modify: frontend files touched by the W10/W13 commits (History↔error-report deep-link wiring, Drafts/Settings mutation error-report capture) — enumerate the exact set live via a merge-base-relative diff (`git diff --stat origin/main...feat/w10-cross-page-deeplink`, triple-dot) at execution time, not a plain two-dot diff — the branch forked from `origin/main` many commits ago, and a two-dot diff would pull in unrelated drift from everything that's landed on `origin/main` since (files this branch never touched)
- Test: the existing spec files colocated with each modified page/component

**Approach:** re-verify at execution time that `feat/w10-cross-page-deeplink` still contains only the W10+W13 commits and nothing else has landed on it since planning; rebase/merge it onto the current `origin/main` tip; open one PR covering both units; resolve any conflicts additively (port forward, don't mechanically pick a side, per Rounds 3's established practice); run the full frontend suite (vitest, typecheck, build) and the relevant backend suite before merging; merge once CI is green or only pre-existing, already-known-unrelated failures remain (e.g. the ongoing `mypy` debt noted as out of scope in every prior round).

**Execution note:** run the branch's own and the full local test suite after any conflict resolution, not just until textual conflict markers disappear — every prior round's own conflict resolutions surfaced real gaps (stale test selectors, missing schema fields, SLOC ceiling drift) that conflict markers alone didn't show.

**Test scenarios:**
- Integration: after merging, re-run the full frontend vitest suite and confirm no already-migrated route's redirect/parity behavior regressed.
- Integration: re-measure `monolith_budget.toml`/`complexity_budget.toml` against the merged tree; if either ceiling is now exceeded, raise it in the same PR with an ≥80-char rationale (matching every prior round's own pattern).
- Edge case: if `origin/main` has moved since this plan's research (likely, given the observed pace of concurrent merges), re-verify the PR is still cleanly mergeable immediately before merging rather than trusting this document's snapshot (R9) — if it no longer is, resolve conflicts fresh rather than assuming the conflict-free state found during planning still holds.

**Verification:** PR opened for `feat/w10-cross-page-deeplink`; CI green (or only pre-existing unrelated failures remain, explicitly confirmed as such); merged; `origin/main` advances to include both W10 and W13.

- [x] **Unit 3: Confirm and prune `docs/u4-test-measurement` (stale, content already landed)** — both signals (CC-30 backstop test, measurement doc) re-verified present on `origin/main`. Archive-tagged, pruned via `scripts/prune-stale-worktrees.sh --dry-run` confirmation + manual removal (script's `--force` would have also swept up `bp-baseline-preref`, explicitly out of scope — removed only this one worktree directly).

**Goal:** remove a branch+worktree whose entire unique content is independently confirmed already on `origin/main`.

**Requirements:** R3, R4, R8, R9

**Dependencies:** None

**Files:** none (git operation only)

**Approach:** re-verify live that `origin/main` still contains the CC-30 complexity-backstop test (`tests/test_no_complexity_regrowth.py`) and `docs/solutions/test-failures/post-fleet-merge-full-suite-measurement-2026-07-06.md` (both confirmed present as of this plan's research); if confirmed, tag `archive/docs-u4-test-measurement`, push the tag to `origin`, delete the local branch and `origin` ref. For the `bp-u4-measure` worktree itself, use the sanctioned `scripts/prune-stale-worktrees.sh --dry-run` (per `AGENTS.md:450`) to confirm it's detected as safe-to-remove before removing it — the script doesn't archive-tag or delete the remote branch, so those steps stay manual.

**Test scenarios:** Test expectation: none -- deleting content already present on `main` under a different commit history, no behavior change.

**Verification:** `archive/docs-u4-test-measurement` tag exists on `origin`; branch and worktree gone; `origin/main` unaffected.

- [x] **Unit 4: Confirm and prune `fix/main-mypy-breakage` (stale, content already landed via PR #83)** — PR #83 re-confirmed `MERGED`. Archive-tagged and pruned. Note: worktree directory removal hit a Windows file lock ("device or resource busy") both here and for `bp-u6-health-dashboard` in Unit 5 — git's own worktree registration was cleanly removed in both cases (confirmed via `git worktree list`), but the empty directory itself resisted deletion; `bp-fix-main-mypy`'s directory is still on disk as harmless empty cruft as of this writing (`bp-u6-health-dashboard`'s cleared on retry).

**Goal:** remove a branch+worktree whose mypy-fix content already merged under PR #83.

**Requirements:** R3, R4, R8, R9

**Dependencies:** None

**Files:** none

**Approach:** re-verify PR #83 (`fix: resolve main's CI breakage (mypy errors + stale redirect-target tests)`) remains `MERGED`; tag `archive/fix-main-mypy-breakage`, push, delete local+remote branch. For the `bp-fix-main-mypy` worktree, use `scripts/prune-stale-worktrees.sh --dry-run` first to confirm it's detected as safe-to-remove, same as Unit 3.

**Test scenarios:** Test expectation: none.

**Verification:** same pattern as Unit 3.

- [x] **Unit 5: Prune the remaining already-merged branches/worktrees** — all 18 originally-listed candidates re-verified as live ancestors of `origin/main` and pruned, plus `integration/w8-w11-w15-frontend` (the branch this plan's own document-review pass caught as dropped from the original inventory). Once Unit 2 completed, `feat/w13-mutation-error-reporting` and `integration/2026-07-06-005-...` were pruned too (the latter via content-verification, confirmed redundant with what Unit 2 established). `feat/w8-spa-shell-upgrade`/`bp-w8-shell` and `bp-baseline-preref` left untouched throughout, exactly as scoped.

**Goal:** clear out the branches confirmed as ancestors of `origin/main`, keeping the workspace legible for the next round.

**Requirements:** R2, R4, R5, R8, R9

**Dependencies:** Unit 2 (so `feat/w13-mutation-error-reporting` and `integration/2026-07-06-005-w1-w2-w4-w5-w6-w10-w12-w13-w14-w15` can be included once W10/W13 land on `main` through Unit 2's PR)

**Files:** none

**Approach:** for each candidate, re-verify live via `git merge-base --is-ancestor <branch> origin/main` immediately before acting (R8/R9 — do not trust this table): `chore/w14-blueprint-audit`, `chore/w8-icon-tweaks` (confirmed to sit at `origin/main`'s own tip commit at planning time — re-verify this still holds, since `origin/main` moves fast in this workspace), `feat/u6-health-dashboard-spa` (+ `bp-u6-health-dashboard` worktree — confirm only the untracked `.context/compound-engineering/ce-code-review/u6-review/` review-artifact dir remains, not real uncommitted work), `feat/w1-refresh-defaults`, `feat/w11-table-a11y`, `feat/w12-responsive-splitscreen`, `feat/w15-neverrun-frontend-guidance`, `feat/w2-settings-edit-protection`, `feat/w4-history-soft-delete`, `feat/w5-history-undo-ux`, `feat/w6-shared-form-system`, `feat/w8-sidenav-icon-badge`, `fix/u16-u1-closeout` (+ `bp-u16-closeout` worktree, confirmed clean), `fix/w15-never-run-health-projection`, `integration/w-batch-1-w1-w2-w6-w4`, `integration/w-batch-2`, `integration/w4-w5-w10-w13-reintegrate-u5`, `integration/w8-w11-w15-frontend` (confirmed merged via a live check during this plan's own document-review pass — its absence from the original candidate list was itself a research gap this plan's review caught; a live recheck at execution time is still required like every other candidate here, per R8/R9), plus, once Unit 2 completes: `feat/w13-mutation-error-reporting` and `feat/w10-cross-page-deeplink` itself (archive-tag and delete once its PR has merged — GitHub's merge-and-delete convention may already remove the remote branch, but tag it regardless per R4, matching Round 3's precedent of archive-tagging merged-PR source branches).

`integration/2026-07-06-005-w1-w2-w4-w5-w6-w10-w12-w13-w14-w15` does **not** go through the ancestor-check above — it never will satisfy it, even after Unit 2 merges, because it's a distinct commit object carrying the same content via a different merge topology (confirmed live: `git merge-base --is-ancestor` returns false for it right now, while its unique file content diffs to zero against `origin/main` once `chore/w14-blueprint-audit`'s own separately-merged history is accounted for). Apply the same content-verification method Units 3/4 use instead: confirm its content is fully redundant with what Unit 2's merge and `chore/w14-blueprint-audit` already landed on `origin/main`, then archive-tag and delete it on that basis.

For each confirmed-ancestor or confirmed-redundant branch: archive-tag, push tag, delete the branch. For the two worktree-backed candidates in this unit (`bp-u6-health-dashboard`, `bp-u16-closeout`), use `scripts/prune-stale-worktrees.sh --dry-run` (per `AGENTS.md:450`) to confirm each is detected as safe-to-remove before removing the worktree — same pattern as Units 3/4; the archive-tag/push/branch-delete steps stay manual since the script doesn't cover them. The remaining candidates here have no worktree, so removal is just the branch-delete step.

**Explicitly excluded (R5):** `feat/w8-spa-shell-upgrade` / `bp-w8-shell` (live uncommitted edits — leave untouched), `bp-baseline-preref` (out of scope, already resolved by Round 3).

**Test scenarios:** Test expectation: none -- deleting refs already fully merged into `main`.

**Verification:** `git branch -a` shows only `main` plus any branch that re-verification found still genuinely unmerged or active; every archive tag present on `origin`; `bp-w8-shell` untouched and still exactly as dirty as found at plan time.

- [x] **Unit 6: Refresh `AGENTS.md`'s branch/worktree documentation** — replaced the round-3-dated block with a round-4 summary reflecting this round's actual outcome (including the Unit 2 rescope and the confirmed-live-active `bp-w8-shell` exclusion). Committed directly to `main` (`b1ff0682`).

**Goal:** keep `AGENTS.md`'s branch section accurate for whoever runs the next round.

**Requirements:** R7

**Dependencies:** Units 3, 4, 5

**Files:**
- Modify: `AGENTS.md` (the branch/worktree documentation block, currently around line 311-318)

**Approach:** replace the Round-3-dated block with a Round-4-dated summary: which PR(s) merged (Unit 2's), which branches were pruned this round (with their archive tag names), and what remains presumed-active concurrent WIP (`bp-w8-shell` only, if still true at execution time — re-check rather than assuming).

**Test scenarios:** Test expectation: none -- documentation only, no application behavior change.

**Verification:** `AGENTS.md` accurately reflects the post-Unit-5 branch state; committed to `main`.

## System-Wide Impact

- **Interaction graph:** no other open PRs exist at planning time, so Unit 2's PR has no sibling-PR file-overlap risk to check — re-verify this holds at execution time too, since new PRs may have opened since.
- **State lifecycle risks:** the dominant risk, as in every prior round, is a concurrent session mutating branches/worktrees/PR state mid-unit. Mitigated by R8/R9 (re-verify and escalate-on-mismatch) and by archive-tagging every deletion before it happens (R4).
- **Unchanged invariants:** `gitlab` remote stays exactly as-is; `bp-w8-shell` and `bp-baseline-preref` stay byte-for-byte untouched throughout; every branch this plan prunes is confirmed an ancestor of `origin/main` (or independently content-verified stale) before deletion, never assumed.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Concurrent-session mutation of branches/worktrees/PRs mid-plan (observed in every prior round) | R8/R9: every unit re-verifies live state immediately before acting; anything showing live edits is left untouched |
| Misclassifying a branch as stale from ahead-count alone, when it actually holds real unlanded work | R3: `docs/u4-test-measurement` and `fix/main-mypy-breakage` were verified stale by content (specific files/tests confirmed present on `origin/main`), not by commit-count heuristics; the same content-verification standard applies to any new ahead-looking branch discovered at execution time |
| A deletion turns out wrong despite verification | R4: archive-tag every deletion first, pushed to `origin`, independent of reflog retention or this workspace's survival |
| `feat/w10-cross-page-deeplink`'s merge conflicts (if `origin/main` has moved further by execution time) resolved mechanically instead of by intent | Execution note on Unit 2: run full test suites after every resolution, not just until conflict markers disappear |

## Sources & References

- Prior rounds: `docs/plans/2026-07-02-002-chore-branch-pr-consolidation-plan.md`, `docs/plans/2026-07-06-006-opt-master-convergence-optimization-plan.md`, `docs/plans/2026-07-06-007-refactor-branch-pr-merge-consolidation-plan.md`
- Source plan for W10/W13 and all other W-numbered units: `docs/plans/2026-07-06-005-opt-webui-uiux-comprehensive-plan.md`
- `AGENTS.md:311-318, 450` — stale-branch documentation and `prune-stale-worktrees.sh` reference (refreshed by Unit 6)
- `docs/solutions/workflow-issues/verify-repo-state-before-planning-2026-05-18.md`, `multi-agent-turf-check-before-claiming-work-2026-05-20.md`, `scan-parallel-prs-before-blocker-2026-05-18.md`, `push-early-committed-survives-branch-deletion-2026-05-27.md`, `foreign-agent-wip-spreads-across-worktrees-2026-05-20.md`, `external-agent-edits-in-shared-worktree-2026-05-18.md`
- `docs/solutions/test-failures/post-fleet-merge-full-suite-measurement-2026-07-06.md`
- PRs merged since Round 3's closeout: #77 (attention-dashboard), #78 (debt-registry fix), #79 (DataTable/pagination U5), #80 (Windows encoding), #81 (U6 health-dashboard SPA), #82 (u16 closeout), #83 (main mypy breakage fix)
- PRs from this round: #84 (opened, closed unmerged — see Addendum), #85 (Settings mutation error-report coverage, merged)

## Addendum (2026-07-07): Unit 2's rescope

The single most consequential discovery this round: `feat/w10-cross-page-deeplink` (and the `feat/w13-mutation-error-reporting` commit it carried) was **not** the sole unlanded copy of W10/W13 that planning-time research believed it to be. A separate branch, `integration/w4-w5-w10-w13-reintegrate-u5` (already merged into `main` by the time this plan's execution began), had independently carried a more advanced implementation of the same units into `main` — its `DraftsPage.vue` was integrated with the later U5 pagination/DataTable rewrite in a way `feat/w10-cross-page-deeplink`'s copy predated, so merging the latter as planned would have silently reverted that integration.

This was only caught because Unit 2's execution ran an actual 3-way merge (`git merge --no-commit --no-ff`) rather than trusting `git merge-tree`'s dry-run output, which had reported zero conflicts at planning time against an earlier `origin/main` tip. By execution time `origin/main` had moved and PR #84 showed real `CONFLICTING` status on GitHub; investigating *why* rather than resolving conflicts file-by-file surfaced the redundancy — and, on closer inspection, that main's competing implementation was strictly better, not just different. The lesson for future rounds of this recurring task: when a "simple merge" unit suddenly shows conflicts against a branch believed to be purely additive, treat it as a signal to check for a parallel reintegration path before resolving conflicts mechanically.

Net effect: the plan's assumed 1-PR Unit 2 became close-1-PR (#84, unmerged) + hand-port-7-files + open-1-new-PR (#85, merged) + prune-1-extra-redundant-branch (`integration/2026-07-06-005-...`). The final tree state matches the plan's intent either way — `main` now has full W10/W13 coverage including Settings, which it lacked before this round — just reached by a narrower, more surgical path than planned.
