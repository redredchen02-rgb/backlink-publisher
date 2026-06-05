---
date: 2026-05-26
topic: tech-debt-cleanup
---

# Tech Debt Cleanup — 2026-05-26

## Problem Frame

Local main is 13 commits behind origin/main (most debt already merged by concurrent agents).
Two decompositions remain uncommitted in the dirty main worktree, plus one open PR to review.

## Requirements

**Local main sync**
- R1. Rescue the plan_check three-tier decomposition from dirty main → feature branch → PR.
  Files: `plan_check.py` (945→305), `_plan_check_format.py`, `_plan_check_git.py`, `_plan_check_schema.py`, test patch, budget ceiling 620→260.
- R2. Rescue the footprint decomposition from dirty main → same or sibling PR.
  Files: `footprint.py` (shrunken), `_footprint_baseline.py`, test patch.
- R3. After branching off the new work, `git pull` local main to origin/main HEAD.
- R4. Discard dirty state in main that is already present in origin/main (projector, fetch, publish_backlinks, reconcile, duplicate untracked files).

**Open PR**
- R5. Review PR #253 (remove beehiiv/cnblogs/habr/ghost). If tests pass and there are no conflicts, merge it.

**Untracked plan docs**
- R6. Commit the orphaned plan docs (2026-05-26-003 through 007 + brainstorm docs) to avoid future confusion.

## Success Criteria
- `git status` on local main shows clean (no untracked WIP from this session)
- PR for plan_check+footprint decomposition is open and tests are green
- PR #253 is merged or a clear reason to defer is documented

## Scope Boundaries
- Do NOT touch stash@{0} (do-not-pop, concurrent session WIP)
- Do NOT touch stash@{1} or stash@{2}
- Do NOT reset or force-push main

## Next Steps
→ `/ce:work` — execute R1–R6 sequentially


## Outcome (2026-06-01)

Shipped → `docs/plans/2026-05-18-002-refactor-phase0-unblock-actions-plan.md` (status: completed); `docs/plans/2026-05-18-003-fix-pytest-bug-sweep-plan.md` (status: completed); `docs/plans/2026-05-18-005-refactor-open-pr-landing-cleanup-plan.md` (status: completed).