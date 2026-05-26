---
title: Commit WIP to Named Branch Then Merge Fast-Forward Instead of Reset
date: 2026-05-26
category: best-practices
module: git
problem_type: best_practice
component: development_workflow
severity: high
applies_when:
  - main has uncommitted WIP anchored on an older base that diverged from origin
  - upstream main has diverged via a revert that deleted files present in the WIP tree
  - git reset --hard is blocked by the pre-bash-safety hook
  - origin/main is a linear descendant of current HEAD (fast-forward is possible)
  - stash-pop would conflict due to deleted files in the upstream diff
symptoms:
  - "pre-bash-safety hook blocks: git reset --hard origin/main"
  - working tree has 40+ modified/untracked files with no clean path to reset
  - WIP base contains files deleted by an upstream revert commit
  - git stash pop leaves working tree in partially-applied conflict state
tags:
  - git
  - wip-preservation
  - ff-only-merge
  - safety-hook
  - branch-instead-of-stash
  - revert-conflict
  - development-workflow
  - dirty-worktree
---

# Commit WIP to Named Branch Then Merge Fast-Forward Instead of Reset

## Context

The main worktree had 45 modified files of uncommitted WIP (a deep-optimization
refactor) anchored on commit `f927fd0`. That commit pre-dated a revert which
deleted 18 platform adapter files and `webui_app/api/*` from `origin/main`.

Attempting `git reset --hard origin/main` to restore main cleanly was blocked by
the pre-bash-safety hook ("Destructive command detected. Requires explicit user
confirmation"). Attempting `git stash -u && reset && pop` would have conflicted:
the stash snapshot includes patches for files the revert had already deleted.

Since `origin/main` (`5c1a7b8`) is a linear descendant of the current HEAD
(`f927fd0`), the working tree could be advanced using `merge --ff-only` — a
non-destructive pointer move — once the WIP was safely committed to its own
branch. (auto memory [claude])

## Guidance

**When main has uncommitted WIP anchored on a divergent base, commit it to a
named branch first, then advance main with `merge --ff-only`.**

```bash
# Step 1: Commit all WIP (tracked + untracked) to a named branch,
#         preserving the divergent base as the branch anchor.
git switch -c wip/deep-optimization
git add -A
git commit -m "wip: deep-optimization refactor snapshot anchored on f927fd0

Uncommitted work preserved off main so main can advance to origin.
Rebase or cherry-pick after relevant PRs land."

# Step 2: Advance main without reset --hard.
git switch main
git merge --ff-only origin/main
# Fast-forward: f927fd0..5c1a7b8
# HEAD is now at origin/main; working tree is 0 dirty files.

# 3. Later — once relevant PRs land, rebase WIP onto updated main.
git switch wip/deep-optimization
git rebase main   # or: git cherry-pick <range>
```

**Prerequisite check — confirm fast-forward is actually possible:**

```bash
git merge-base --is-ancestor HEAD origin/main && echo "ff possible" || echo "diverged — use rebase instead"
```

If this exits non-zero, origin/main is not a descendant of the current HEAD.
In that case, rebase the WIP branch onto origin/main first, then use a different
strategy to clean main.

## Why This Matters

`git reset --hard` is blocked by design — it discards uncommitted work without
recovery. The branch + ff-only pattern achieves the same cleanup without
bypassing any safety rails:

- **Stash pop fails when upstream deleted files** that the WIP touches. `git stash
  pop` applies working-tree patches; a patch for a file the target state has
  deleted raises a merge conflict, leaving the working tree partially applied.
  In this case the upstream revert removed 108 files between the WIP base and
  `origin/main`.
- **`merge --ff-only` is non-destructive.** It only succeeds when local HEAD is a
  strict linear ancestor of the target — the branch pointer simply advances, and
  the working tree moves cleanly with no data loss.
- **A named branch preserves coherence.** The WIP snapshot is pinned to its
  original base, making it safely rebaseable onto the new `origin/main` tip once
  the relevant PRs land. It can be pushed to origin (`git push origin wip/...`)
  to prevent it from being pruned by `prune-stale-worktrees.sh`.
- **Post-merge hooks fire as expected.** If a post-merge hook detects WebUI-
  relevant changes, it will restart background services automatically — this is
  normal, not an error.

## When to Apply

- The main worktree has uncommitted WIP and you need to advance HEAD to origin/main
- `git reset --hard` is blocked by the pre-bash-safety hook or you want to avoid it
- The WIP base and origin/main diverge by **deleted files** (stash pop would conflict)
- You need the WIP preserved in a rebaseable form for later cherry-pick or rebase
- Any time you need to move a dirty worktree to a clean state without data loss

## Examples

**Broken approach — stash pop conflicts on deleted files:**

```bash
# origin/main deleted 18 adapter files that exist in your WIP base
git stash -u
git reset --hard origin/main   # BLOCKED: pre-bash-safety hook fires
git stash pop                  # CONFLICT: patch for deleted beehiiv_api.py, etc.
# working tree in broken partially-applied state
```

**Correct approach — branch pins the base, ff-only advances cleanly:**

```bash
# 1. Pin WIP to its own branch
git switch -c wip/deep-optimization
git add -A
git commit -m "wip: snapshot anchored on f927fd0"

# 2. Advance main
git switch main
git merge --ff-only origin/main   # → Fast-forward: f927fd0..5c1a7b8

# 3. Push the WIP branch so prune-stale-worktrees.sh won't delete it
git push origin wip/deep-optimization

# 4. Verify clean state
git status              # clean
git log --oneline -1    # HEAD at origin/main tip
git branch | grep wip   # wip/deep-optimization preserved
```

## Related

- [`docs/solutions/workflow-issues/foreign-agent-wip-spreads-across-worktrees-2026-05-20.md`](../workflow-issues/foreign-agent-wip-spreads-across-worktrees-2026-05-20.md) — WIP spread via concurrent agents (different root cause; same principle: investigate before force-cleaning)
- [`docs/solutions/workflow-issues/scaffold-worktree-commit-before-writes-2026-05-20.md`](../workflow-issues/scaffold-worktree-commit-before-writes-2026-05-20.md) — commit first so prune-stale-worktrees.sh doesn't delete new worktree content
- [`docs/solutions/workflow-issues/external-agent-edits-in-shared-worktree-2026-05-18.md`](../workflow-issues/external-agent-edits-in-shared-worktree-2026-05-18.md) — stage explicit files, not `git add -A`, when a worktree may have concurrent edits
- [`docs/solutions/workflow-issues/cherry-pick-to-main-when-parent-pr-blocks-ci-2026-05-19.md`](../workflow-issues/cherry-pick-to-main-when-parent-pr-blocks-ci-2026-05-19.md) — clean-worktree strategy when a stacked PR needs to be retargeted
