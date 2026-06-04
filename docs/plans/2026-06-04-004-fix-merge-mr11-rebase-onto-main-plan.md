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
- **Sync POST recheck stays**: `fix/keep-alive-recheck-button` adds a synchronous route distinct from the async job added by `feat/keepalive-loop-r1`; both should coexist
- **Force-push with lease**: use `--force-with-lease` to avoid overwriting concurrent GitLab commits on the feature branch

## Open Questions

### Resolved During Planning

- **Does `feat/keepalive-loop-r1` add a recheck route that conflicts?** Yes, it adds async job endpoints in `keep_alive.py`; the sync POST from MR !11 must be integrated alongside them
- **GitHub push needed?** No — account suspended; GitLab is the live trunk

### Deferred to Implementation

- **Exact conflict lines**: determined at rebase time; cannot predict without running the rebase

## Implementation Units

- [ ] **Unit 1: Commit untracked plan file**

**Goal:** Clean working tree before rebase

**Dependencies:** None

**Files:**
- Add: `docs/plans/2026-06-04-003-feat-ai-content-engine-pro-mode-wiring-plan.md` (new untracked file, stage + commit)

**Approach:**
- `git add docs/plans/2026-06-04-003-...` then commit with message `docs: add AI content engine pro mode wiring plan`

**Test scenarios:**
- Test expectation: none — pure docs commit, no behavioral change

**Verification:**
- `git status` shows clean working tree after commit

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

**Goal:** Land MR !11 commits on top of updated `main`

**Dependencies:** Unit 2

**Files:**
- `webui_app/routes/keep_alive.py` — expected conflict
- `webui_app/static/js/keep_alive.js` — expected conflict
- `webui_app/templates/keep_alive.html` — expected conflict

**Approach:**
- `git checkout fix/keep-alive-recheck-button && git rebase main`
- For `routes/keep_alive.py`: keep both the async job routes (from `main`) and the sync POST recheck route (from MR !11); they serve different endpoints and should coexist
- For `keep_alive.js`: retain async job wiring from `main` and add the `fetch()` handler for `#recheckBtn` from MR !11 alongside it
- For `keep_alive.html`: retain async job UI from `main` and integrate the flash alert block + enabled button from MR !11

**Test scenarios:**
- Test expectation: none at this unit — conflicts are content merges, not logic changes; tested in Unit 4

**Verification:**
- `git rebase --continue` completes without error
- `git log --oneline main..HEAD` shows exactly 2 commits (SHAs will differ from pre-rebase values — rebase rewrites them)

---

- [ ] **Unit 4: Run tests**

**Goal:** Verify rebased branch passes all tests

**Dependencies:** Unit 3

**Files:**
- Test: `tests/test_webui_keep_alive_recheck.py`
- Test: `tests/test_webui_route_contract.py`

**Approach:**
- `PYTHONHASHSEED=0 PYTHONPATH=src pytest tests/ -x` from `backlink-publisher/` directory
- Focus on keep_alive and route_contract tests; known pre-existing failures in `test_webui_equity_ledger_recheck.py` are trunk-level and do not block this MR (per MR !11 description)

**Test scenarios:**
- Happy path: `test_webui_keep_alive_recheck.py` — 5 tests pass (happy path, empty store, GET flash render, no-flash baseline, button enabled)
- Integration: route_contract gate includes `/ce:keep-alive` POST endpoint
- Error path: empty store redirects with `flash_type=info`, no 500

**Verification:**
- All tests in `tests/test_webui_keep_alive_recheck.py` green
- No new test failures beyond pre-existing trunk failures

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

- **Unchanged invariants:** CSRF guard, route contract gate, existing keep-alive async job endpoints — none of these change behavior; the sync POST recheck is additive
- **Error propagation:** MR !11 adds a flash redirect on error; failure during recheck returns `flash_type=error`, not a 500
- **Integration coverage:** `test_webui_route_contract.py` enforces route surface parity — it must stay green

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Rebase conflict in `keep_alive.py` harder than expected | Both branches add distinct endpoints; resolve by keeping all new routes |
| `--force-with-lease` blocked by concurrent GitLab activity | Check for swarm activity before pushing; push to a unique branch if blocked |
| Pre-existing `equity_ledger_recheck` failures mask real failures | Run targeted `test_webui_keep_alive_recheck.py` first; ignore known pre-existing failures |
| GitHub origin accumulates more drift | Out of scope; push when account is restored |

## Sources & References

- Related code: `webui_app/routes/keep_alive.py`, `webui_app/static/js/keep_alive.js`
- GitLab MR !11: https://gitlab.com/redredchen01/backlink-publisher/-/merge_requests/11
- Memory: `gitlab-push-via-glab-credential-helper` — non-interactive push requires glab helper
- Memory: `dedicated-merge-swarm-autolands-worktrees` — check if swarm is active before pushing
