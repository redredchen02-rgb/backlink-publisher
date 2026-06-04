---
title: "fix: Rebase fix/keep-alive-recheck-button onto main and merge MR !11"
type: fix
status: active
date: 2026-06-04
---

# fix: Rebase fix/keep-alive-recheck-button onto main and merge MR !11

## Overview

MR !11 (`fix/keep-alive-recheck-button` → `main`) is open on GitLab but has diverged from the current `gitlab/main` (`88e0a57`). After `feat/keepalive-loop-r1` was merged into `gitlab/main`, three files overlap between the two branches. This plan covers: committing the untracked plan file, updating local `main`, rebasing the feature branch, resolving conflicts, running tests, and merging the MR.

## Problem Frame

- `gitlab/main` moved from `d746825` → `88e0a57` (merged `feat/keepalive-loop-r1`) after `fix/keep-alive-recheck-button` was cut
- Both branches modify `webui_app/routes/keep_alive.py`, `webui_app/static/js/keep_alive.js`, `webui_app/templates/keep_alive.html`
- MR !11 cannot be merged cleanly until the branch is rebased and conflicts resolved

## Scope Boundaries

- GitHub (`origin`) is suspended — push there only, no PRs needed
- Only GitLab MR !11 is in scope; `origin/feat/notesio-adapter` and `origin/refactor/webui-config-cache-governance` are out of scope
- No new features; this is a pure merge-hygiene operation

## Context & Research

### Relevant Code and Patterns

- `webui_app/routes/keep_alive.py` — both branches added routes here; `feat/keepalive-loop-r1` added async job routes, `fix/keep-alive-recheck-button` added sync POST recheck
- `webui_app/static/js/keep_alive.js` — `feat/keepalive-loop-r1` added async job wiring; `fix/keep-alive-recheck-button` added `fetch()` handler for sync recheck button
- `webui_app/templates/keep_alive.html` — both branches updated flash and button rendering
- `docs/plans/2026-06-04-003-feat-ai-content-engine-pro-mode-wiring-plan.md` — untracked file that must be committed first

### GitLab credential helper

Per project memory: non-interactive `git push gitlab` requires `git -c credential.https://gitlab.com.helper='!glab auth git-credential' push`

## Key Technical Decisions

- **Rebase over merge**: rebase keeps MR !11 linear on GitLab; a local merge commit would add noise to the MR diff
- **Async version wins at `POST /ce:keep-alive/recheck`**: both branches register a handler at the same URL — feature branch has sync 302 redirect, `main` has async 202 JSON (`start_recheck()`). Flask cannot register two handlers; take `main`'s async version entirely and discard the feature branch's `keep_alive_recheck()`. The recheck button was already enabled by `feat/keepalive-loop-r1`.
- **Force-push with lease**: use `--force-with-lease` to avoid overwriting concurrent GitLab commits on the feature branch
- **Plan files go to main, not MR !11**: commit `docs/plans/2026-06-04-003-*` and `docs/plans/2026-06-04-004-*` (this plan) to `main` directly so MR !11 diff stays clean

## Open Questions

### Resolved During Planning

- **Does `feat/keepalive-loop-r1` conflict at the route URL?** Yes — both branches register `POST /ce:keep-alive/recheck`. Flask cannot hold two handlers. Resolution: keep `main`'s async `start_recheck()`, discard the feature branch's sync `keep_alive_recheck()`; the entire sync path (`test_webui_keep_alive_recheck.py`, flash block, `fetch()` handler) is superseded.
- **GitHub push needed?** No — account suspended; GitLab is the live trunk

### Deferred to Implementation

- **Exact conflict lines**: determined at rebase time; cannot predict without running the rebase

## Implementation Units

- [ ] **Unit 1: Clean working tree — commit docs to main, stage settings fix to feature branch**

**Goal:** Ensure rebase starts from a clean working tree; keep MR !11 diff free of unrelated docs

**Dependencies:** None

**Files:**
- Add to `main`: `docs/plans/2026-06-04-003-feat-ai-content-engine-pro-mode-wiring-plan.md`, `docs/plans/2026-06-04-004-fix-merge-mr11-rebase-onto-main-plan.md`
- Modify on `fix/keep-alive-recheck-button`: `webui_app/templates/_settings_llm_integration.html` (stage + commit as standalone fix)

**Approach:**
- Step A: `git checkout main` → `git add docs/plans/2026-06-04-003-... docs/plans/2026-06-04-004-...` → commit `docs: add plan-003 AI content engine and plan-004 MR merge plan` → fast-forward to `gitlab/main` (Unit 2 can follow immediately)
- Step B: `git checkout fix/keep-alive-recheck-button` → inspect `_settings_llm_integration.html` diff → stage + commit with an appropriate one-line message
- After Step B: `git status` must show clean working tree before proceeding to Unit 3

**Test scenarios:**
- Test expectation: none — docs and template config commits, no behavioral change

**Verification:**
- `git log --oneline main | head -1` includes the docs commit
- `git status` on `fix/keep-alive-recheck-button` shows clean working tree

---

- [ ] **Unit 2: Sync local main with gitlab/main**

**Goal:** Bring local `main` to `88e0a57`

**Dependencies:** Unit 1

**Files:**
- Local `main` branch (fast-forward only)

**Approach:**
- `git checkout main && git merge --ff-only gitlab/main`
- If fast-forward fails, local `main` has diverged — investigate before proceeding

**Test scenarios:**
- Test expectation: none — branch pointer update only

**Verification:**
- `git log --oneline -1 main` shows `88e0a57`

---

- [ ] **Unit 3: Rebase fix/keep-alive-recheck-button onto main**

**Goal:** Land MR !11 docs commit on top of updated `main`; discard superseded sync-route code

**Dependencies:** Unit 2

**Files:**
- `webui_app/routes/keep_alive.py` — conflict: **take `main`'s version entirely** (discard `keep_alive_recheck()`)
- `webui_app/static/js/keep_alive.js` — conflict: **take `main`'s version entirely** (discard `fetch()` handler for `#recheckBtn`)
- `webui_app/templates/keep_alive.html` — conflict: **take `main`'s version entirely** (drop flash block; `main` has async job progress UI and republish panel)
- `tests/test_webui_route_contract.py` — conflict: **take `main`'s version entirely** (main has the full expanded `TestKeepAliveRoutes` with all 6 action routes; feature branch only covered GET)
- `tests/test_webui_keep_alive_recheck.py` — **DELETE**: tests the sync 302-redirect contract which is superseded by the async route; keeping it would produce 5 permanent failures

**Approach:**
- `git checkout fix/keep-alive-recheck-button && git rebase main`
- On each conflict, run `git checkout --theirs <file>` (take main's version) for all four files above
- For `tests/test_webui_keep_alive_recheck.py`: `git rm tests/test_webui_keep_alive_recheck.py` during conflict resolution (it was added by `f36f532`; after taking main's async route, its 302-redirect assertions permanently fail)
- After resolving all conflicts: `git rebase --continue`
- **If `f36f532` becomes an empty commit** after all code changes are discarded: `git rebase --skip` (the commit's functional content is entirely superseded; only `5d91bbc` — docs update — has non-empty changes post-rebase)

**Test scenarios:**
- Test expectation: none at this unit — conflict resolution is a content selection, not logic change; verified in Unit 4

**Verification:**
- `git rebase --continue` or `--skip` completes without error
- `git log --oneline main..HEAD` shows 1–2 commits (SHAs will differ from pre-rebase values — rebase rewrites them); `5d91bbc` docs commit must be present

---

- [ ] **Unit 4: Run tests**

**Goal:** Verify rebased branch passes all tests

**Dependencies:** Unit 3

**Files:**
- Test: `tests/test_webui_keepalive_recheck_route.py` (async route contract — 202/403/409)
- Test: `tests/test_webui_keepalive_recheck_job.py` (async job lifecycle)
- Test: `tests/test_webui_keepalive_republish.py` (republish path)
- Test: `tests/test_webui_route_contract.py` (full route coverage gate)

**Approach:**
- Run targeted tests first: `PYTHONHASHSEED=0 PYTHONPATH=src pytest tests/test_webui_keepalive_recheck_route.py tests/test_webui_keepalive_recheck_job.py tests/test_webui_keepalive_republish.py tests/test_webui_route_contract.py -v`
- If those pass, run full suite: `PYTHONHASHSEED=0 PYTHONPATH=src pytest tests/ -x` — ignore known pre-existing failures in `test_webui_equity_ledger_recheck.py`

**Test scenarios:**
- Happy path: async recheck POST returns 202 with job_id
- Error path: duplicate recheck returns 409; unauthenticated returns 403
- Integration: `test_webui_route_contract.py` route coverage gate includes all 6 async keepalive action routes

**Verification:**
- All four targeted test files green
- No new failures beyond pre-existing trunk baseline

---

- [ ] **Unit 5: Force-push and merge MR !11**

**Goal:** Land `fix/keep-alive-recheck-button` on GitLab and close MR !11

**Dependencies:** Unit 4

**Files:**
- Remote: `gitlab/fix/keep-alive-recheck-button`
- Remote: `gitlab/main`

**Approach:**
- `git -c credential.https://gitlab.com.helper='!glab auth git-credential' push --force-with-lease gitlab fix/keep-alive-recheck-button`
- Then merge MR !11 on GitLab: `glab mr merge 11 --squash=false --delete-source-branch`
- Confirm: `git fetch gitlab && git log --oneline -1 gitlab/main` shows the merge commit

**Test scenarios:**
- Test expectation: none — git push + remote merge; result verified by fetching new main HEAD

**Verification:**
- MR !11 status shows `merged`
- `gitlab/main` moves past `88e0a57` to include both recheck commits

---

- [ ] **Unit 6: Clean up local branches**

**Goal:** Remove stale local branches after merge

**Dependencies:** Unit 5

**Files:**
- Local branches: `fix/keep-alive-recheck-button`, `feat/internal-edition-lite-keepalive`

**Approach:**
- `git checkout main && git merge --ff-only gitlab/main`
- `git branch -d fix/keep-alive-recheck-button` (already merged)
- `git branch -d feat/internal-edition-lite-keepalive` (already merged in `d2b97c2`)

**Test scenarios:**
- Test expectation: none — branch pointer cleanup

**Verification:**
- `git branch` shows only `main` locally

## System-Wide Impact

- **Unchanged invariants:** CSRF guard, route contract gate, all existing async keep-alive endpoints — none change behavior; this rebase is purely a merge-hygiene operation landing a docs commit
- **Superseded by feat/keepalive-loop-r1:** The functional intent of MR !11 (enabling the recheck button) is already present in `gitlab/main`; the rebase lands only the `5d91bbc` docs commit (`f36f532`'s code changes are discarded as superseded)
- **test_webui_keep_alive_recheck.py deleted:** The sync 302-redirect test file is removed during conflict resolution; async coverage lives in `test_webui_keepalive_recheck_route.py`
- **Integration coverage:** `test_webui_route_contract.py` enforces route surface parity — it must stay green

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `f36f532` becomes empty after discarding all code conflicts | Use `git rebase --skip` — the commit's functional content is superseded; docs commit `5d91bbc` still lands |
| `--force-with-lease` blocked by concurrent swarm activity | Check `git fetch gitlab` before pushing; if blocked, push to a unique branch name |
| Pre-existing `equity_ledger_recheck` failures mask real failures | Run targeted async keepalive tests first before full suite |
| Unit 6 tries to delete `feat/internal-edition-lite-keepalive` before verifying it merged | Run `git branch --merged main` to confirm before `git branch -d` |
| GitHub origin accumulates more drift | Out of scope; push when account is restored |

## Sources & References

- Related code: `webui_app/routes/keep_alive.py`, `webui_app/static/js/keep_alive.js`
- GitLab MR !11: https://gitlab.com/redredchen01/backlink-publisher/-/merge_requests/11
- Memory: `gitlab-push-via-glab-credential-helper` — non-interactive push requires glab helper
- Memory: `dedicated-merge-swarm-autolands-worktrees` — check if swarm is active before pushing
