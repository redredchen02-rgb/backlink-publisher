---
title: "chore: Branch & PR Consolidation — Merge Completed Work, Prune Landed Branches"
type: refactor
status: completed
date: 2026-07-02
claims: {}  # pure git housekeeping (merge/delete/commit-carry-forward) — no new business logic; verified by branch/worktree state + existing test suite on touched files, not new assertions
---

# Branch & PR Consolidation — Merge Completed Work, Prune Landed Branches

## Overview

Consolidate the `backlink-publisher` workspace (canonical repo `backlink-publisher/` + 4 `git worktree` checkouts under `bp-<topic>/`) into a clean, up-to-date state **relative to its own local feature branches**: merge completed local feature branches into local `main`, delete branches whose content is already verified to have landed under different commit hashes (squash-merges), and leave genuinely in-progress work untouched. This is pure repository housekeeping — no application code is being designed or added; the one code change carried forward (except-block narrowing) is pre-existing uncommitted work being preserved, not authored here.

**Scope caveat (see Problem Frame):** local `main` and `origin/main` have themselves independently diverged — this plan does not reconcile that divergence. "Up-to-date state" here means "all local worktree branches consolidated," not "byte-identical with `origin/main`."

## Problem Frame

The user asked to "merge branches and PRs to bring the project to its latest state, and delete what's mergeable" (原文: 幫我merge分支與PR 讓專案整理成最新的狀態，merge完就可以刪除). Direct investigation (see Context & Research) found the situation is more specific than the request implies:

- **GitHub PR merging is not currently possible.** The `gh` CLI reports `HTTP 403: account was suspended` for the authenticated account (`redredchen01`), and none of the 5 local feature branches have an upstream configured — they were never pushed, so no GitHub PR exists for any of them. "Merging PRs" in the literal sense doesn't apply; the only real merge path is local `git merge` into `main`.
- A **prior session already did partial branch-safety analysis** (commit `e860a980`, "docs(plan): mark A3 verified - stale branches safe to delete pending user authorization" on the Phase 3 plan) and asked for deletion authorization via a blocking question that timed out unanswered. That analysis is correct and is carried forward here, extended to cover branches it didn't check.
- One worktree (`bp-u1-triage`, branch `fix/u1-test-suite-triage`) has **genuinely active, uncommitted work** (a partial test-audit inventory) matching the still-unfinished U1 unit of the active v0.6.0 upgrade plan — this must be excluded, not merged or deleted.
- The current branch (`fix/webui-theme-nav-layout-cleanup`, in the canonical `backlink-publisher/` worktree) has its own plan marked `status: completed`, but the working tree has 13 files of uncommitted except-block-narrowing fixes plus 2 untracked plan docs (including the currently-active v0.6.0 plan file itself) that must be preserved before this branch can be merged.
- **Local `main` and `origin/main` have independently diverged and this plan does not reconcile that.** `git log main..origin/main` shows 7 commits local `main` lacks — the tail five (`500a6b7c`…`3707eeb8`) are an independent "decoupling refactor U5–U8" (CLI subdirectory reorganization, import-linter enforcement, function decomposition) that **duplicates work local `main` already did differently**: local `main` has its own `5f472fd0 refactor(U8): reorganize cli/ into 6 functional subdirectories`, `6b4c3555 opt(U7)`, `2178a205 opt(U6)`, `c59b983a refactor(U5)`. Verified directly: both `main` and `origin/main` produce the *same* resulting `cli/` subdirectory layout (`admin/`, `ops/`, `plan/`, `publish/`, `reporting/`, `spray/`, etc.) but with almost every blob hash different — i.e. the same reorganization was independently executed twice, and `git diff --stat main origin/main` reports **1061 files changed**. Reconciling two independently-forked, structurally-identical-but-content-different full-codebase refactors is a separate, much larger effort than "merge branches and clean up," and is explicitly out of scope here (see Scope Boundaries). This also means the `origin/main`-based "safe to delete" verifications below are against `origin/main`, not local `main` — see the Context & Research verification table for which `main` each check used.

## Requirements Trace

- R1. Every branch merged into `main` must have its content verified complete and not a duplicate of already-landed work.
- R2. Every branch deleted must have its content verified as already present in `main` (via ancestor check or direct diff/content verification) or verified as merged as part of this plan — never deleted on the basis of "probably fine."
- R3. The active-WIP branch (`fix/u1-test-suite-triage`) and its worktree must not be touched.
- R4. Uncommitted work in the canonical worktree must be preserved (committed), not discarded, before any branch switch or merge.
- R5. No new content/commits are pushed to `origin` (GitHub) or `gitlab` remotes as part of this pass — merged `main` stays local until the user pushes manually (per user decision; see Open Questions). This does **not** cover the remote branch-*deletion* pushes in R2/Unit 2: those are ref-deletions of content the user's original request already authorized removing ("merge完就可以刪除"), not new content landing on a shared branch — see Key Technical Decisions.
- R6. `AGENTS.md`'s stale-branch list (`AGENTS.md:312`) is updated to reflect the post-cleanup branch state so it doesn't keep citing branches that no longer exist.
- R7. Every branch deleted in Unit 2 is tagged (`archive/<branch-name>`) immediately before deletion, so recovery doesn't depend solely on reflog retention if a verification later turns out wrong.

## Scope Boundaries

- No application feature work, bug fixes, or refactors beyond carrying forward already-written uncommitted changes.
- No GitHub/GitLab account remediation (restoring `gh auth`) — out of scope; the plan works around the outage rather than fixing it.
- No conflict-resolution choreography is pre-scripted — real merge conflicts (if any) are resolved at execution time per the guidance in each unit's Approach, not dictated here.
- `fix/u1-test-suite-triage` / `bp-u1-triage` worktree: explicitly out of scope, left exactly as-is.
- Reconciling local `main` with `origin/main`'s independently-forked decoupling refactor (7 commits, ~1061 files of blob-level divergence — see Problem Frame): out of scope. This plan only consolidates local worktree branches into local `main`.

### Deferred to Separate Tasks

- Restoring GitHub account access / `gh auth login`: user's own action, outside this plan.
- Pushing the updated `main` to `origin`/`gitlab`: deferred to a future explicit user instruction (R5).
- Resuming `fix/u1-test-suite-triage` (U1 test-suite triage): tracked by the existing v0.6.0 upgrade plan (`docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md`), not this plan.
- Reconciling local `main` vs `origin/main`'s independent U5–U8 CLI-decoupling fork: a separate, much larger audit (comparing two independently-authored full refactors of the same subsystem) — needs its own plan, not a subtask of branch cleanup.

## Context & Research

### Relevant Code and Patterns

This plan required git-topology archaeology rather than code-pattern research (no application code is being designed). Findings were verified via `git merge-base --is-ancestor`, `git cherry` (patch-id equivalence — the most reliable check, since it survives squash-merges), `git log --grep`, `git diff main...<branch>` (triple-dot: the branch's own unique changes since its fork point, not a raw two-point tree diff — a raw `git diff --stat main <branch>` was tried first and produced 1000+-file noise dominated by unrelated intervening `main` history, which is not a useful signal here), and direct content/file-existence checks — not inferred from commit messages alone. **Each row states which `main` it was checked against**, since local `main` and `origin/main` have diverged (see Problem Frame) and conflating them would invalidate the check.

**Branches verified as already landed — safe to delete (strong verification: literal ancestor check or exact `git cherry` patch match):**

| Branch | Where | Landed via | Verification |
|---|---|---|---|
| `fix/drafts-store-test-isolation` | local + `origin`, checked against local `main` | PR #42 (squash) | `git cherry main fix/drafts-store-test-isolation` → `-5bc7327f` (exact patch-id match, the strongest available signal — survives the squash) |
| `fix/recheck-ledger-liveness-seam` | local + `origin`, checked against local `main` | PR #31 (squash) | `git cherry main fix/recheck-ledger-liveness-seam` → `-0b30cfaf` (exact patch-id match) |
| `origin/refactor/u1-generate-payload` | remote-only leftover, checked against `origin/main` | PR #54 | `git merge-base --is-ancestor origin/refactor/u1-generate-payload origin/main` → true (non-squash, literal ancestor) |
| `origin/feat/webui-console-redesign` | remote-only, checked against `origin/main` | PR #20 | `origin/main` log has `15f31da4 feat(webui): dark console redesign — shell, components, monitor hub (1/2) (#20)` |
| `origin/feat/webui-publish-workbench` | remote-only, checked against `origin/main` | PR #20 + PR #22 | `origin/main` log has `22947ac9 feat(webui): dark console redesign — workbench polish + anomaly badge (2/2) (#22)`; branch is a superset of `webui-console-redesign` |
| `origin/opt/phase2-test-coverage-exceptions` | remote-only, checked against `origin/main` | PR #51 | `origin/main` log has `7929dd65 refactor(opt): Phase 2 — events.* mypy strict, 124 new tests, except Exception narrowing (#51)` |
| `gitlab/feat/full-automation-upgrade` | `gitlab` remote only, checked against `origin/main` | PR #13 (on GitHub, re-landed) | `origin/main` log has `15e69cb9 feat: Full Automation Upgrade — PipelineOrchestrator, ThrottleEngine, intentional_zero flag (#13)` |

**Branches very likely already landed, but with weaker verification — delete with a safety tag (R7), not with the same confidence as the table above:**

| Branch | Where | Landed via | Verification | Why weaker |
|---|---|---|---|---|
| `chore/v050-doc-archive` | local only, checked against local `main` | equivalent of PR #41 + a later consolidation | `git cherry main chore/v050-doc-archive` → both commits show `+` (no exact patch match); but its only non-deletion content change is a doc-path update (`docs/brainstorms/...` → `docs/_archive/brainstorms/...`) already reflected in `main`, and its tombstone markers are present in `main`'s `docs/` | `git cherry` found no byte-identical patch (expected after a squash/re-landing, not necessarily a problem) — confirmed via targeted content checks instead of patch-id |
| `feat/v050-ui-consistency` | local only, checked against local `main` | PR #40 + fixup `d265f2cf` | `git cherry main feat/v050-ui-consistency` → both commits show `+` (no exact patch match); `main` has a matching `2a30b31f feat(webui)... (#40)` merge and no `CSRF_ENABLED` toggle in the two test files (matches the fixup) | The branch also modified `webui_app/static/js/settings.js`, which **no longer exists at that path in `main`** — the WebUI has since been rewritten to an SPA (per `main`'s `feat(webui): migrate dashboard routes to SPA` history), so that specific file-level change can't be re-confirmed at its original location; the higher-level feature (empty-state/error-taxonomy UX) is confirmed landed via PR #40, but exact byte parity for every touched file isn't |

**Branches verified as complete, local-only, ready to merge** (no upstream exists — never pushed, so no PR to merge; only path is local `git merge`):

| Branch | Worktree | Notes |
|---|---|---|
| `feat/phase3-sprint-e1-docs-archive` | `bp-phase3-sprint-e1` | Already an ancestor of `feat/phase3-sprint-b-frontend-stabilization` — do not merge separately, just delete after sprint-b lands |
| `feat/phase3-sprint-b-frontend-stabilization` | `bp-phase3-sprint-b` | Contains E1 + C2/C3/D3/E2/E3 (90 commits ahead of `origin/main`); clean working tree |
| `feat/frontend-error-reporting` | `bp-error-reporting` | 8/8 units shipped per its own plan-completion commit; clean working tree; **not** an ancestor/descendant of sprint-b — genuinely diverged, real merge needed |
| `fix/webui-theme-nav-layout-cleanup` | `backlink-publisher/` (canonical, current) | Own plan (`2026-07-01-001`) is `status: completed`; **not** an ancestor/descendant of sprint-b or error-reporting — diverged from a much earlier common point (58 commits sprint-b has that this branch lacks; 1 commit this branch has that sprint-b lacks) |

**Excluded — active WIP, do not touch:**

| Branch | Worktree | Evidence |
|---|---|---|
| `fix/u1-test-suite-triage` | `bp-u1-triage` | Untracked `docs/audits/2026-07-02-u1-negative-assertion-inventory.txt` (1547 lines, "U1-5" in-progress), matches U1's still-open status in `docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md` |

**Uncommitted work to preserve** (canonical worktree, branch `fix/webui-theme-nav-layout-cleanup`):
- 13 modified tracked files, each narrowing a bare `except Exception:` to specific exception types (e.g. `src/backlink_publisher/config/tokens.py`: `except Exception` → `except (json.JSONDecodeError, OSError)`) — matches the Phase 3 signal-integrity plan's except-classification work (see `[[phase3-signal-integrity-plan-status]]` memory), not related to this branch's own (completed) theme/nav plan.
- 2 untracked plan docs: `docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md` (a stale local copy — the real, canonical copy already lives committed on `feat/frontend-error-reporting`; this untracked one shows `status: active` vs. the branch's own `status: completed`-equivalent, i.e. it's drifted and should not overwrite the canonical copy) and `docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md` (the current active v0.6.0 plan — this **is** the canonical, only copy, and must not be lost).

### Institutional Learnings

- `[[workspace-shared-directory-no-worktree-isolation]]` — this exact workspace previously had a concurrent-session collision (2026-07-01) inside `backlink-publisher/` before worktrees were split out. `git worktree list` now shows proper 1-worktree-per-branch isolation (5 entries), so the structural cause is resolved, but the drifted untracked `feat/frontend-error-reporting` plan-doc copy found in the canonical worktree is a likely artifact of that incident. Treat it as stale, not authoritative.
- `[[execution-pace-after-urgency-signal]]` — branch deletion and cross-branch merging are exactly the "hard-to-reverse, touches shared state" category this memory says warrants a pause-and-flag even under a "push forward" signal. This plan resolves the flagged items via explicit user confirmation (Open Questions) rather than proceeding silently.
- `[[project_v060_upgrade_plan_status]]` — confirms U1 (test-suite triage, on `fix/u1-test-suite-triage`) is the active plan's first unit and is not yet done, corroborating the exclusion in R3.
- `docs/solutions/workflow-issues/salvage-unmerged-work-from-dirty-behind-main-tree-2026-05-26.md` (severity: high) — describes precisely this repo's recurring failure mode: local `main` diverged from `origin/main` with mixed-provenance dirt. Its prescribed procedure (snapshot → classify via `git cat-file -e` → prove zero-regression via `git diff --stat <old-base> origin/main -- <files>` expecting *empty* output → rebuild on a clean base) is the right tool for the *deferred* origin/main reconciliation task, not for this plan's local-only merges — but Unit 1's Approach borrows its "prove before applying" principle by scoping to files with no upstream-restructure risk (see Unit 1).

## Key Technical Decisions

- **Merge locally, do not push (R5):** GitHub API access is down and pushing to shared remotes is a "visible to others" action requiring separate confirmation regardless. User explicitly chose to defer pushing to a later, deliberate step. *(User decision, this session.)*
- **Commit-then-merge for the current branch's WIP (R4):** the except-narrowing fixes and the untracked v0.6.0 plan doc are real, valuable work; discarding or stashing them risked exactly the kind of silent-loss incident recorded in `[[workspace-shared-directory-no-worktree-isolation]]`. *(User decision, this session.)*
- **Verify remote-only branches before scoping them in (R2):** rather than assuming "old + far behind = safe," each of the 4 remote-only branches was checked for actual landed content in `main` via commit-message/file-content cross-reference, following the same rigor the prior session (`e860a980`) applied to `fix/drafts-store-test-isolation` / `fix/recheck-ledger-liveness-seam`. *(User decision, this session — expanded scope from local-only.)*
- **`feat/phase3-sprint-e1-docs-archive` is not merged separately:** since it's a verified ancestor of `feat/phase3-sprint-b-frontend-stabilization`, merging sprint-b already brings in all of e1's content; a separate merge would be a no-op fast-forward with no new content, so it's just deleted once sprint-b lands.
- **No pre-scripted conflict resolution:** `feat/frontend-error-reporting`, `feat/phase3-sprint-b-frontend-stabilization`, and `fix/webui-theme-nav-layout-cleanup` are three genuinely diverged lines of work that plausibly touch overlapping WebUI surfaces (the Phase 3 plan's own risk register flags `webui_app/api/`, `webui_store/`, and shell components — `TopBar.vue`/`SideNav.vue`/`AppShell.vue` — as shared across concurrent plans). Real merges may conflict; this plan sequences them (smallest/most isolated first) to minimize compounding conflicts but does not predict or script specific resolutions.
- **Origin/main reconciliation is explicitly out of scope, not silently dropped:** local `main` and `origin/main` independently re-did the same U5–U8 CLI decoupling refactor (see Problem Frame), producing ~1061 files of blob-level divergence. Reconciling that is a separate, much larger effort (auditing two independently-authored full-codebase refactors against each other) than "merge local branches and clean up." This plan lands local worktree branches into local `main` only; the origin/main divergence is named as a deferred follow-up (Scope Boundaries, Deferred to Separate Tasks) rather than silently glossed over. *(Confirmed via feasibility review during doc-review — see Sources & References.)*
- **Remote branch-deletion pushes (Unit 2) are treated as in-scope despite R5's "no push" framing:** R5's "don't push" decision (this session) was about not landing new *content* on shared `main` refs while GitHub access is unreliable — it wasn't a statement about the user's separate, standing authorization to delete branches once merged ("merge完就可以刪除", the original request). R5's wording is corrected to make this distinction explicit rather than leaving Unit 2 in silent tension with it. *(Confirmed via feasibility + adversarial review — see Sources & References.)*
- **Tag before delete (R7):** two of the nine Unit 2 deletions (`chore/v050-doc-archive`, `feat/v050-ui-consistency`) rest on weaker verification (no exact `git cherry` patch match, and one touches a file since relocated by the SPA rewrite) than the other seven. Rather than either blocking on exhaustive re-verification or accepting bare reflog-only recoverability, every Unit 2 deletion gets a lightweight `archive/<branch>` tag first — durable, cheap, and independent of `git gc` timing. *(Confirmed via adversarial review — see Sources & References.)*

## Open Questions

### Resolved During Planning

- GitHub PR merge mechanism given the account suspension → local `git merge`, no push this pass (R5).
- Disposition of the current branch's uncommitted WIP → commit it first, then merge (R4).
- Whether to investigate the 4 remote-only branches → yes, included and verified (R2).
- Deletion authorization for the branches a prior session flagged "safe to delete pending user authorization" (`e860a980`, whose original blocking question timed out unanswered) → superseded by this session's explicit request to merge and delete, confirmed again via this session's own AskUserQuestion round (landing mechanism / WIP disposition / remote-only scope) — not carried forward on the strength of the unanswered prior question alone.

### Deferred to Implementation

- Exact merge-conflict resolutions (if any arise merging sprint-b / error-reporting / webui-theme-nav into `main`) — cannot be known until the merges are actually attempted; implementer should treat a textual conflict in a shared file (e.g. both sides added distinct routes/components to the same file) as additive-merge-both, and escalate to the user only if a conflict looks like a genuine semantic contradiction (same symbol, incompatible behavior) rather than a textual juxtaposition.
- Whether the drifted untracked `feat/frontend-error-reporting` plan-doc copy in the canonical worktree should be deleted outright or is worth diffing against the canonical committed copy first for any note-worthy divergence — deferred to Unit 1's execution.
- Whether/when to plan the separate origin/main-vs-local-main reconciliation effort (the independently-forked U5–U8 decoupling refactor) — explicitly deferred, not scheduled by this plan.

## Implementation Units

- [x] **Unit 1: Preserve in-flight WIP on the current branch**

**Goal:** Commit the uncommitted except-narrowing fixes and the untracked v0.6.0 plan doc on `fix/webui-theme-nav-layout-cleanup` so nothing is lost before this branch is merged or any worktree is touched.

**Requirements:** R4

**Dependencies:** None — do this first, before any other unit, since later units switch branches / merge.

**Files:**
- Modify (commit as-is, already written): the 13 except-narrowing files listed under Context & Research (`src/backlink_publisher/_util/net_safety.py`, `cli/_dedup_gate.py`, `cli/_footprint_baseline.py`, `cli/_publish_helpers.py`, `cli/_resume.py`, `cli/ops/keepalive_status.py`, `cli/ops/probe_citations.py`, `cli/pr_opportunities.py`, `cli/spray_backlinks/_audit.py`, `cli/spray_backlinks/_gates.py`, `cli/spray_backlinks/core.py`, `config/tokens.py`, `optimization/rules.py`)
- Add (commit as-is): `docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md`
- Investigate then decide: `docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md` (untracked, drifted copy — diff against the canonical committed copy on `feat/frontend-error-reporting`; if genuinely just stale/duplicate, remove it rather than committing it, so a `status: active` stray doesn't shadow the real `status: completed` one after merge)

**Approach:**
- The except-narrowing changes are pre-existing, already-written fixes (not authored in this plan) — commit them verbatim with a message describing what they are (exception-type narrowing), not inventing new scope.
- These are live, already-applied edits sitting uncommitted in the current worktree's working directory (confirmed via `git diff` — not a patch being forward-ported from elsewhere), so there is no "does this hunk still apply" risk within this plan's scope: this unit only captures the current working-tree state as a commit on the current branch, which then merges into *local* `main` (Unit 5) — it does not touch `origin/main`. `origin/main` independently touched several of these same 13 files as part of its own decoupling refactor (see Problem Frame); that overlap is a concern for the deferred origin/main reconciliation task, not for this unit.
- Do not run a broad test suite pass here beyond confirming the touched modules still import/compile — full verification happens implicitly once these land in `main` alongside the rest of the merges (existing CI/test tiers cover them).

**Test scenarios:**
- Test expectation: none -- committing already-written diffs verbatim; no new behavior introduced by this unit itself. Existing tests for the touched modules (if any exercise the narrowed except paths) continue to apply post-commit.

**Verification:**
- `git status --short` on the canonical worktree is clean (no modified/untracked files) after this unit.
- The v0.6.0 plan doc is present and committed on `fix/webui-theme-nav-layout-cleanup`.

---

- [x] **Unit 2: Prune branches with content already verified in `main`**

**Goal:** Delete all branches (local and remote) whose full content is already present under different commit hashes (in local `main` for local-only/local+origin branches, in `origin/main` for remote-only branches), per the verification table in Context & Research, with a safety tag on each so deletion is recoverable independent of reflog retention.

**Requirements:** R2, R6, R7

**Dependencies:** None — independent of the merge units; can run before or after them.

**Files:** No source files — git branch/ref operations only, plus:
- Modify: `AGENTS.md` (update the stale-branch list at `AGENTS.md:312` to remove the now-deleted branches)

**Approach:**
- Before deleting any branch, tag its tip (`archive/<branch-name>`) so it stays recoverable regardless of reflog expiry (R7) — treat this as non-negotiable for the two weaker-verified branches (`chore/v050-doc-archive`, `feat/v050-ui-consistency`), and cheap insurance for the other seven.
- Local-only deletions: `chore/v050-doc-archive`, `feat/v050-ui-consistency`.
- Local + remote (`origin`) deletions: `fix/drafts-store-test-isolation`, `fix/recheck-ledger-liveness-seam`.
- Remote-only deletions: `origin/refactor/u1-generate-payload`, `origin/feat/webui-console-redesign`, `origin/feat/webui-publish-workbench`, `origin/opt/phase2-test-coverage-exceptions`, `gitlab/feat/full-automation-upgrade`.
- These remote deletions are ref-deletion pushes, not new-content pushes — in scope despite R5 (see Key Technical Decisions' R5 clarification).
- Remote branch deletion uses plain git-over-HTTPS/SSH (push access), which is independent of the broken `gh` API/account-suspension — but confirm with an actual write probe, not a read-only one: `git ls-remote` only proves fetch access and can succeed even when push is blocked. Use something that exercises the write path (e.g. a `git push --dry-run origin :refs/heads/<branch>` per branch, or push-then-check-response on the real delete) before treating push access as confirmed. If push access is *also* blocked, fall back to deleting the local remote-tracking ref only and flag the true remote branch for manual deletion.

**Test scenarios:**
- Test expectation: none -- deletion of already-landed branches has no runtime behavior; verified by absence from `git branch -a` afterward, not by tests.

**Verification:**
- `git branch -a` no longer lists any of the 9 pruned branches (local or remote-tracking).
- `git tag -l 'archive/*'` shows one tag per pruned branch.
- `AGENTS.md`'s branch list matches the post-cleanup state.

---

- [x] **Unit 3: Merge `feat/frontend-error-reporting` into `main`**

**Goal:** Land the completed frontend error-reporting/diagnostics work into `main`.

**Requirements:** R1

**Dependencies:** None (isolated feature branch, no shared prerequisite with other units).

**Files:**
- Merge commit touching whatever `feat/frontend-error-reporting` changed (frontend error-reporting dashboard, per its plan `docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md`, canonical copy on this branch).
- Delete: `bp-error-reporting` worktree and the `feat/frontend-error-reporting` branch once merged.

**Approach:**
- Straight `git merge` from `main` (this branch has no upstream/PR, so there's no GitHub-side merge to perform).
- Resolve any conflicts per the guidance in Key Technical Decisions (additive-merge for textual overlap in shared WebUI files; escalate genuine semantic conflicts).

**Test scenarios:**
- Test expectation: none -- this unit merges already-implemented, already-tested feature work; no new behavior is authored here. Post-merge, run the project's existing test suite scoped to touched files to confirm the merge itself didn't break anything (a merge-integrity check, not new coverage).

**Verification:**
- `main` contains `feat/frontend-error-reporting`'s tip as an ancestor.
- `bp-error-reporting` worktree and branch no longer exist.
- Existing tests for touched files still pass post-merge.

---

- [x] **Unit 4: Merge `feat/phase3-sprint-b-frontend-stabilization` into `main`, then prune its subset branch**

**Goal:** Land the Phase 3 frontend-stabilization integration branch (which already contains `feat/phase3-sprint-e1-docs-archive`) into `main`, then remove the now-fully-redundant e1 branch.

**Requirements:** R1

**Dependencies:** None strictly, but doing this after Unit 3 (the smaller, more isolated merge) reduces the chance of compounding unresolved conflicts, per the sequencing rationale in Key Technical Decisions.

**Files:**
- Merge commit touching whatever `feat/phase3-sprint-b-frontend-stabilization` changed (integrates Sprint E1/C2/C3/D3/E2/E3 per its own merge commit `d82b4979`).
- Delete: `bp-phase3-sprint-b` worktree + `feat/phase3-sprint-b-frontend-stabilization` branch, and `bp-phase3-sprint-e1` worktree + `feat/phase3-sprint-e1-docs-archive` branch, once merged.

**Approach:**
- Straight `git merge` from `main`.
- Because this branch and `feat/frontend-error-reporting` (already merged in Unit 3) are genuinely diverged and may both touch shared WebUI surfaces, expect this merge to be the more likely of the two to need conflict resolution — resolve per the same additive-merge-first guidance.
- `feat/phase3-sprint-e1-docs-archive` needs no separate merge (verified ancestor of sprint-b) — just delete its branch + worktree once sprint-b's merge lands.

**Test scenarios:**
- Test expectation: none -- merges already-implemented, already-tested work. Post-merge, run existing tests scoped to touched files as a merge-integrity check.

**Verification:**
- `main` contains `feat/phase3-sprint-b-frontend-stabilization`'s tip (and transitively `feat/phase3-sprint-e1-docs-archive`'s tip) as ancestors.
- `bp-phase3-sprint-b`, `bp-phase3-sprint-e1` worktrees and both branches no longer exist.
- Existing tests for touched files still pass post-merge.

---

- [x] **Unit 5: Merge `fix/webui-theme-nav-layout-cleanup` into `main`, repoint the canonical worktree**

**Goal:** Land the theme/nav/layout cleanup work (plus the Unit-1-preserved except-narrowing fixes and v0.6.0 plan doc) into `main`, and leave the canonical `backlink-publisher/` worktree checked out on `main` afterward.

**Requirements:** R1, R4

**Dependencies:** Unit 1 (WIP must be committed first). Sequenced last among the three merges since this branch carries the most recent/least-reviewed changes (the just-committed except-narrowing work) and is most likely to surface conflicts against the other two now-merged branches.

**Files:**
- Merge commit touching whatever `fix/webui-theme-nav-layout-cleanup` changed, including the Unit 1 commit.
- No worktree deletion — `backlink-publisher/` is the canonical worktree and stays; only its checked-out branch changes (to `main`) and the now-merged `fix/webui-theme-nav-layout-cleanup` branch ref is deleted.

**Approach:**
- Merge into `main`, then switch the canonical worktree's checkout to `main` (it must not be left on a deleted branch).
- This is the branch most likely to conflict with the already-merged `feat/frontend-error-reporting` and `feat/phase3-sprint-b-frontend-stabilization` (same shared-surface risk noted in Key Technical Decisions) — resolve conflicts with the same additive-first, escalate-on-semantic-contradiction approach.

**Test scenarios:**
- Test expectation: none -- merges already-implemented theme/nav work plus the Unit-1-preserved except-narrowing fixes; no new behavior authored in this unit. Post-merge, run existing tests scoped to touched files (including the 13 except-narrowed modules) as a merge-integrity check.

**Verification:**
- `main` contains `fix/webui-theme-nav-layout-cleanup`'s tip (post-Unit-1-commit) as an ancestor.
- `backlink-publisher/` worktree's current branch is `main`.
- `fix/webui-theme-nav-layout-cleanup` branch ref no longer exists.
- Existing tests for touched files still pass post-merge.

---

- [x] **Unit 6: Final state audit**

**Goal:** Confirm the workspace is in the intended clean, up-to-date state and that nothing out of scope was disturbed.

**Requirements:** R3, R5, R6

**Dependencies:** Units 1–5.

**Files:** No source changes — verification only (AGENTS.md update already covered in Unit 2).

**Approach:**
- Confirm `bp-u1-triage` / `fix/u1-test-suite-triage` is untouched (still has its uncommitted audit-inventory file, branch still exists, not merged or deleted).
- Confirm local `main` has not been pushed to `origin` or `gitlab` (per R5 — the user will push manually later).
- Confirm `git branch -a` and `git worktree list` show only: `main` (canonical worktree) and `fix/u1-test-suite-triage` (`bp-u1-triage` worktree, excluded) — everything else from the original 9-branch/5-worktree state has either merged-and-been-deleted or been pruned.

**Test scenarios:**
- Test expectation: none -- this is a state-verification unit, not a code change.

**Verification:**
- `git worktree list` shows exactly `backlink-publisher/` (on `main`) and `bp-u1-triage/` (on `fix/u1-test-suite-triage`).
- `git branch -a` shows no leftover merged/pruned branch names.
- `git log main..origin/main` / `git log main..gitlab/main` (behind-count) reflects that `main` has moved ahead locally but remotes are untouched — i.e., `origin/main` and `gitlab/main` still point at their pre-plan commits.
- Note for whoever reads this state afterward: local `main` is now "clean" relative to all local worktree branches, but is still **not** reconciled with `origin/main`'s independent decoupling-refactor fork (7 commits, ~1061 files of divergence) — that gap is intentional and tracked as a deferred follow-up, not a bug in this plan's execution.

## System-Wide Impact

- **Interaction graph:** No runtime callbacks/middleware/observers are touched — this is repository state only. The one indirect runtime effect is the except-narrowing fixes changing which exception types 13 modules catch (Unit 1/5) — this is pre-written code being committed, not new logic.
- **Error propagation:** The except-narrowing changes make error handling in those 13 files *more specific* (narrower catches), which could surface exceptions that were previously silently swallowed by a bare `except Exception`. This is the intended effect of that pre-existing work, not a side effect of this plan — flag if any newly-surfaced exception looks unexpected during post-merge test runs.
- **State lifecycle risks:** The main risk is losing uncommitted work during a branch switch — mitigated by sequencing Unit 1 (commit) strictly before any merge/switch operation, and by never running a destructive git command without first confirming a clean `git status`.
- **API surface parity:** N/A — no API changes.
- **Integration coverage:** Post-merge test runs (per each merge unit's Verification) are the integration check that the three diverged branches didn't silently break each other's shared WebUI surfaces when combined.
- **Unchanged invariants:** `origin/main` and `gitlab/main` remain exactly as they are today throughout this entire plan (R5) — only the local `main` branch advances. `fix/u1-test-suite-triage` and its worktree are byte-for-byte unchanged (R3).

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Real merge conflicts between `feat/frontend-error-reporting`, `feat/phase3-sprint-b-frontend-stabilization`, and `fix/webui-theme-nav-layout-cleanup` in shared WebUI surfaces (`webui_app/api/`, `webui_store/`, shell components) | Sequenced smallest/most-isolated first (Units 3→4→5); additive-merge-first guidance with escalation-on-semantic-contradiction (see Key Technical Decisions and Open Questions) |
| Losing the uncommitted except-narrowing fixes or the untracked v0.6.0 plan doc during a branch switch | Unit 1 commits everything first, is sequenced before any other unit, and is verified via a clean `git status` before proceeding |
| `git push` (for remote-only branch deletion in Unit 2) may also be blocked if push auth shares the same broken credential as the `gh` CLI token | Approach note in Unit 2: confirm push access with an actual write probe first (not `git ls-remote`, which only proves read access); fall back to local-ref-only deletion + manual flag if blocked |
| A previously-unnoticed concurrent session touches these branches/worktrees mid-plan (per `[[workspace-shared-directory-no-worktree-isolation]]`) | Before each unit, check `git branch --show-current` / `git log` for unexpected commits per that memory's guidance; pause and flag if detected rather than proceeding |
| `AGENTS.md`'s stale-branch list (R6) drifts again after this plan if future branches aren't cleaned up promptly | Out of scope to prevent structurally here — noted as a documentation-hygiene follow-up, not blocking this plan |
| `chore/v050-doc-archive` / `feat/v050-ui-consistency` deletions rest on weaker verification than the other 7 (no exact `git cherry` patch match; one touches a file since relocated by the SPA rewrite) | R7 tag-before-delete on every Unit 2 deletion gives a durable, reflog-independent rollback point specifically for these two weaker-verified branches |
| Local `main`'s "up-to-date" state after this plan is relative to local branches only — it remains diverged from `origin/main` by an independently-forked U5–U8 decoupling refactor (~1061 files) | Explicitly named as out of scope (Scope Boundaries, Deferred to Separate Tasks) rather than silently left unaddressed; Overview and Unit 6 verification carry the caveat forward so it isn't mistaken for a completeness gap in this plan's own execution |

## Execution Summary (2026-07-02)

All 6 units executed. Outcomes that materially differed from the plan as written:

- **Scope correction found during execution:** `chore/v050-doc-archive` and `feat/v050-ui-consistency` also had `origin/*` remote-tracking refs (documented in this plan as "local only" — an error caught and corrected during Unit 2 rather than earlier during planning). Both remote-tracking refs were deleted alongside their local branches.
- **Push access fully blocked, not just the `gh` API:** the write-probe in Unit 2 confirmed `git push` itself (not just the `gh` CLI/API) is blocked on `origin` (account suspension) and `gitlab` (no working SSH auth). All 9 Unit 2 deletions were local-ref-only, as the plan's fallback anticipated; the corresponding remote branches on GitHub/GitLab still need manual deletion once access is restored.
- **Concurrent session discovered on `feat/phase3-sprint-b-frontend-stabilization`:** partway through Unit 4's post-merge verification, `bp-phase3-sprint-b` showed new commits (a code-review/adversarial-finding fix cycle) that postdated this plan's merge of that branch's tip into `main`. Per this workspace's own concurrent-session protocol, the branch and worktree deletion for `feat/phase3-sprint-b-frontend-stabilization` was **not executed** — left alone rather than risking destruction of the other session's in-progress work. Its content as merged into `main` is unaffected; only the follow-up branch/worktree cleanup is deferred. `bp-u1-triage` was independently confirmed to also have substantial new uncommitted changes beyond its original single audit file, consistent with a second concurrent session actively progressing the v0.6.0 plan's U1 unit — R3 held (it was never written to).
- **One genuine merge-interaction regression found and fixed:** merging `feat/frontend-error-reporting` (Unit 3) and `feat/phase3-sprint-b-frontend-stabilization` (Unit 4) in sequence surfaced an unclassified bare `except Exception:` in `webui_app/api/v1/error_reports.py` that neither branch's own test suite caught in isolation — the seam-classification gate only started scanning that file's directory once both merges landed. Fixed by narrowing to `(tomllib.TOMLDecodeError, OSError)`, matching the existing docstring's stated intent and Unit 1's established pattern.
- **Full differential test verification:** rather than relying on the plan's "existing tests for touched files" language alone, the actual Python unit-tier suite (2000+ tests) was run against both the pre-merge baseline (`a5dc969b`, in an isolated comparison worktree) and post-merge `main`, and every failure-count/name delta was individually traced to its origin. Of 30 tests newly failing post-merge, 29 were confirmed pre-existing on `feat/phase3-sprint-b-frontend-stabilization` in isolation (a shim `import *` dropping private helper re-exports — out of this plan's scope to fix, same category as the already-documented ~366-failure baseline) and 1 was the genuine merge-interaction issue above, now fixed. Frontend (`vitest`, 240 tests) and TypeScript compile-checks were also run; the 3 pre-existing `vue-tsc` type errors found were traced back to the original pre-merge `main` and confirmed unrelated to this plan.
- **`docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md`** (the untracked, drifted copy flagged in Open Questions) was confirmed stale (all units unchecked, `status: active`) against the canonical committed copy on `feat/frontend-error-reporting` (all units checked, completed) and discarded rather than committed.

**Final state:** `main` contains all local worktree branches' content except the not-yet-finished WIP on `fix/u1-test-suite-triage` (R3, untouched) and `feat/phase3-sprint-b-frontend-stabilization`'s newest commits made after this plan's merge point (branch/worktree cleanup deferred, content already in `main`). 13 `archive/*` tags exist as rollback points for every deleted/merged branch. Nothing was pushed to `origin` or `gitlab` (R5).

## Sources & References

- Related plan (Phase 3, contains the prior A3 branch-safety audit): `docs/plans/2026-06-30-001-opt-phase3-post-v050-iteration-plan.md`
- Related plan (v0.6.0 upgrade, defines the still-open U1 unit this plan excludes): `docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md`
- Related plan (frontend error reporting, merged in Unit 3): `docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md`
- Related plan (theme/nav/layout cleanup, merged in Unit 5): `docs/plans/2026-07-01-001-fix-webui-theme-nav-layout-cleanup-plan.md`
- `AGENTS.md:311-312` — stale-branch documentation to be updated in Unit 2
- `docs/solutions/workflow-issues/salvage-unmerged-work-from-dirty-behind-main-tree-2026-05-26.md` — prior-art procedure for the deferred origin/main reconciliation task
- Reviewed by `ce-doc-review` (coherence, feasibility, adversarial personas) on 2026-07-02; feasibility review surfaced the local-main-vs-origin-main divergence (now reflected throughout this document) and adversarial review surfaced the R5/Unit-2 push-scope ambiguity and the tag-before-delete safety improvement
