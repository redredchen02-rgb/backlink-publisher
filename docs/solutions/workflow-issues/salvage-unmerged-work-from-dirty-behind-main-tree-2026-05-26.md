---
title: "Salvage only genuinely-unmerged work from a dirty, behind-origin, concurrently-contested main tree"
date: 2026-05-26
category: docs/solutions/workflow-issues
module: git workspace hygiene + bp-*/ worktrees
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - "local main is several commits behind origin/main AND dirty with mixed-provenance changes"
  - "the dirty tree tangles already-merged PR leftovers, genuinely-new work, and a foreign edit from another branch's lineage"
  - "a concurrent agent is reshaping the workspace mid-operation (worktrees/branches/PRs moving)"
  - "you must land ONLY the unmerged work in a clean isolated PR without losing anything or colliding"
root_cause: missing_workflow_step
resolution_type: workflow_improvement
tags:
  - git
  - dirty-worktree
  - wip-salvage
  - concurrent-agent
  - foreign-edit-exclusion
  - monolith-budget
  - plan-claims-gate
  - development-workflow
related_components:
  - tooling
---

# Salvage only genuinely-unmerged work from a dirty, behind-origin, concurrently-contested main tree

## Context

In a shared canonical git repo that uses `bp-*` sibling worktrees and is operated
by **multiple concurrent agents**, the local `main` working tree drifted into a
dangerous three-way mess at the same time:

1. It was **~8–10 commits behind `origin/main`** (the intervening merges were PRs
   #242–#250).
2. It was **dirty**, and the dirt was heterogeneous:
   - **(a) Stale uncommitted copies of already-merged work** — local edits that
     duplicate what PRs #242–#250 already landed. Committing these would *regress*
     merged work.
   - **(b) Genuinely-unmerged new work** — two monolith-budget extractions
     (`events/projector.py` helpers → `_project_helpers.py`, and a
     `cli/publish_backlinks.py` epilogue extraction) that exist nowhere on origin.
     This is the only thing worth saving.
   - **(c) A FOREIGN hunk** — a `monolith_budget.toml` ceiling edit
     (`adapters` `680 → 760`) inherited from a *different branch's* lineage.
     Smuggling this into the salvage PR would launder an unrelated, unowned change
     into `main`.

Either naive move loses or corrupts data:

- `git reset --hard origin/main` destroys category (b), the real WIP.
- `git add -A && commit` regresses (a) and smuggles (c).

This is distinct from the simpler "advance a clean-but-behind main" case
(see [Related](#related)): here you cannot fast-forward and you cannot treat the
whole dirty tree as one coherent WIP branch, because the dirt has three different
origins. You must **classify each file**, **prove zero regression**, and **rebuild
on a clean base** — all without touching the shared `main` that another agent is
actively reshaping.

## Guidance

Work in this exact order. The ordering *is* the safety property: snapshot before
surgery, classify before salvage, prove before applying, isolate before validating.

**1. SNAPSHOT FIRST — copy the entire dirty tree to `/tmp` before any git surgery.**
Nothing can be lost if a raw copy exists outside git's control.

```bash
SNAP=/tmp/wip-snapshot-$(date +%Y%m%d-%H%M%S)
for f in $(git status --short | awk '{print $2}'); do
  mkdir -p "$SNAP/$(dirname "$f")"; cp "$f" "$SNAP/$f"
done
git diff > "$SNAP/tracked.diff"; git stash list > "$SNAP/stash-list.txt"
```

**2. CLASSIFY each dirty file — does it already exist on `origin/main`?**

```bash
git cat-file -e origin/main:<path>   # exit 0 ⇒ exists on origin
```

- **Exists on origin** ⇒ likely a **stale already-merged duplicate** (category a).
  Leave it behind.
- **Missing on origin** ⇒ **genuinely new** (untracked plan docs, new helper
  modules — category b). Salvage candidate.
- Note: `git cat-file -e` exits **128** (not 1) for a missing path and prints
  `does not exist in` to stderr — discriminate on the stderr substring, and pin
  `LC_ALL=C LANG=C`, rather than trusting the exit code alone. See the
  `git cat-file` gotcha doc under [Related](#related).

**3. PROVE the salvage files weren't touched by the intervening merges
(zero-regression check).**

```bash
git diff --stat <old-local-main-sha> origin/main -- <salvage-file-1> <salvage-file-2>
```

**Empty output = proof**: the commits between your stale base and `origin/main`
never touched those files, so your local WIP applies cleanly onto `origin/main`
with no regression risk. If output is non-empty, you have a real conflict to
resolve by hand — do not blind-copy.

**4. REBUILD on a clean worktree cut from `origin/main`** (NOT from the dirty local
main). Place it at the **sibling level (`../`)**, never nested inside the repo — a
nested worktree pollutes the parent as untracked files.

```bash
git worktree add ../bp-foo origin/main
# If you accidentally nested it:
git worktree remove bp-foo && git worktree add ../bp-foo origin/main
```

**5. Copy ONLY the verified-unmerged files** from the snapshot into the new
worktree. Leave the stale already-merged copies (category a) behind entirely.

**6. For MIXED files, hand-apply ONLY your hunks.** `monolith_budget.toml` carried
both your two extraction ceilings AND the foreign `adapters 680 → 760` hunk. Apply
your hunks via targeted edits; **deliberately exclude** the foreign lineage's hunk,
then verify the excluded value still matches origin:

```bash
git show origin/main:monolith_budget.toml | grep -A1 adapters   # confirm still 680, not 760
```

**7. VALIDATE in the worktree with the sibling-worktree incantation.**
`PYTHONPATH=src` is **mandatory** — without it the editable install resolves to the
*canonical* worktree's `src/` and you silently test the wrong tree.

```bash
PYTHONHASHSEED=0 PYTHONPATH=src pytest tests/        # → 5021 passed / 6 skipped
radon raw -s src/backlink_publisher/events/projector.py   # confirm SLOC/budget claims
```

**8. Commit on the isolated branch, push, open the PR.** Only ever operate on your
own branch.

## Why This Matters

A single wrong git verb here is **irreversible data loss or a silent regression in
`main`**:

- `reset --hard` would have erased two real extractions that existed nowhere else.
- `add -A && commit` would have un-done four merged PRs *and* laundered an unowned
  foreign config change into `main`.

The snapshot → classify → prove → isolate sequence converts an irreversible
decision into a reversible, verifiable one. The
`git diff --stat <old-base> origin/main -- <files>` empty-output check is the
linchpin: it's a cheap, mechanical **proof** that copying WIP forward causes zero
regression — replacing guesswork with evidence.

The concurrent-agent dimension is what makes this genuinely hard. In a repo where
another agent is reshaping shared `main` in real time, the usual "tidy up the
working tree" reflexes become hostile actions against another worker. Isolation
isn't politeness — it's the only way two agents can both finish without colliding.

**Outcome:** PR #254 merged to `origin/main` (squash `4c76edb`); full suite
**5021 passed / 6 skipped**; zero data loss; no collision with the concurrent agent.

## When to Apply

Apply the **full procedure** when *all* of these hold:

- Local `main` (or any working tree) is **both dirty and behind** its upstream.
- The dirt is **heterogeneous** — you cannot assume "all dirty = my unmerged work."
- The repo is **shared** (worktree siblings and/or multiple concurrent agents).

Apply **individual steps** standalone:

- **Step 1 (snapshot)** — before *any* destructive git surgery on a dirty tree.
- **Step 2 (`cat-file` classify)** — whenever you need to know if a local file is a
  merged duplicate or genuinely new.
- **Step 3 (`diff --stat` proof)** — any time you forward-port WIP onto a moved base
  and need to rule out regression.
- **Steps 4 + 7 (sibling worktree + `PYTHONPATH=src`)** — whenever you build/test in
  a `bp-*` worktree of this repo.

**Concurrent-agent guardrail (critical, applies throughout):** Re-run
`git worktree list` and `git branch -vv` between phases. The moment you observe the
**shared `main` working tree being actively reshaped by another agent** — worktrees
appearing/disappearing, branches advancing, `main` growing NEW unrelated WIP, PRs
self-merging — **STOP all destructive cleanup**: no `reset --hard` on main, no
deleting branches or worktrees you don't own. Clean **only your own** isolated
worktree/branch, and only after your PR merges:

```bash
git worktree remove ../bp-foo
git branch -D <your-branch>
```

## Examples

**Classify: merged-duplicate vs genuinely-new:**

```bash
git cat-file -e origin/main:src/.../_project_helpers.py   # 128 + "does not exist in" ⇒ new, salvage
git cat-file -e origin/main:src/.../fetch.py              # exit 0 ⇒ already-merged, leave behind
```

**Zero-regression proof (empty output = safe to forward-port):**

```bash
git diff --stat <old-local-main-sha> origin/main -- \
  src/backlink_publisher/events/projector.py \
  src/backlink_publisher/cli/publish_backlinks.py
# (no output) ⇒ intervening merges never touched these files
```

**Mixed file — apply your hunks, exclude the foreign one, then verify:**

```bash
# Edit monolith_budget.toml: add ONLY the projector + publish_backlinks ceilings.
# Do NOT carry the foreign adapters 680 -> 760 hunk.
git show origin/main:monolith_budget.toml | grep -A1 adapters   # confirm still 680
```

**CI gotcha — `plan-claims-gate` failure on an included plan doc dated on/after the
2026-05-20 cutoff:**

```yaml
# Plan doc frontmatter — opt out when the implementing SHAs aren't merged yet:
claims: {}
```

```bash
# Verify locally BEFORE re-push:
python -m backlink_publisher.cli.plan_check docs/plans/<doc>.md; echo $?   # expect 0
```

**Cleanup — only your own worktree/branch, only after merge:**

```bash
git worktree remove ../bp-budget-rescue
git branch -D opt/monolith-budget-rescue
```

## Related

- [`wip-branch-ff-merge-instead-of-reset-2026-05-26.md`](../best-practices/wip-branch-ff-merge-instead-of-reset-2026-05-26.md) — the **simpler sibling case**: when the whole dirty tree is one coherent WIP and `origin/main` is a clean descendant, commit WIP to a named branch and `merge --ff-only` instead of this classify-and-rebuild dance. Use that when the dirt is *homogeneous*; use this doc when it is *mixed-provenance*.
- [`foreign-agent-wip-spreads-across-worktrees-2026-05-20.md`](./foreign-agent-wip-spreads-across-worktrees-2026-05-20.md) — concurrent-agent dirty-tree detection; supports the "stop destructive cleanup when a concurrent agent is detected" guardrail.
- [`multi-agent-turf-check-before-claiming-work-2026-05-20.md`](./multi-agent-turf-check-before-claiming-work-2026-05-20.md) — turf-check worktrees/branches before acting; dirty main on arrival may be another agent's WIP.
- [`external-agent-edits-in-shared-worktree-2026-05-18.md`](./external-agent-edits-in-shared-worktree-2026-05-18.md) — stage explicit files, never `git add -A`, in a contested worktree (supports excluding foreign hunks).
- [`per-worktree-venv-vs-pythonpath-2026-05-19.md`](../developer-experience/per-worktree-venv-vs-pythonpath-2026-05-19.md) — `PYTHONPATH=src` vs per-worktree `.venv` for editable-install isolation (the Step 7 verification).
- [`git-cat-file-exits-128-not-1-2026-05-20.md`](../logic-errors/git-cat-file-exits-128-not-1-2026-05-20.md) — `git cat-file -e` exits 128 not 1; discriminate via stderr (the Step 2 classifier gotcha).
