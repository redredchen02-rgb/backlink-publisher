---
status: pending
priority: p1
issue_id: "012"
tags: [reliability, data-integrity, hardening-sweep, debt-registry]
dependencies: []
---

# debt_registry.toml entry misclassifies a silent events.db write failure as recoverable "temporary staleness" when it is actually permanent data loss

## Problem Statement

D3 (`docs/plans/2026-07-06-002-opt-hidden-debt-hardening-sweep-plan.md`) added a `debt_registry.toml` entry, `publish-writer-events-db-write-degrade-open-medium`, classifying `events/publish_writer.py`'s swallowed `events.db` write failures as `severity = "medium"` / `status = "open"` on the theory that a dropped write is "a temporary staleness window closed by the next dashboard read" via `webui_app/helpers/history.py`'s prior `publish-history.json` write and `events/reconcile.py::project_on_read`'s re-derivation. The reliability code-review pass (run `20260706-140906-a92c9d99`) found this recovery path no longer exists in the current codebase — the classification understates a genuine, permanent silent-data-loss risk.

## Findings

- `webui_app/helpers/history.py`'s own docstring: "As of U2, events.db is the sole write target — `history_store` is no longer written here." There is no `publish-history.json` write happening in this path to serve as a backstop.
- `src/backlink_publisher/_util/history_write.py::append_published_rows` (the only function that would write `publish-history.json`) has zero callers outside its own test file — confirmed dead code via `grep -rn "append_published_rows" --include="*.py" . | grep -v /tests/`.
- `events/reconcile.py::project_on_read` re-derives from `EventStore` itself (its own internal projection state), not from `publish-history.json` — it cannot recover an event that was never durably written to `events.db` in the first place.
- Conclusion: if `events/publish_writer.py`'s `write_event`/`write_publish_result` swallow a write failure (lines ~67, 206, 212), there is currently no independent data source to recover the lost publish-result record from. This is permanent silent data loss for the affected publish, not staleness that resolves on the next read.
- The registry entry's own justification requirement (K8 step 2: "an independent recheck... a genuinely different code path and data source") is not actually satisfied — the plan's own framework would likely classify this as `open-high` or `fix-now`, not `open-medium`, if the dead-code fact were known at classification time.

## Proposed Solutions

### Option 1: Correct the debt_registry.toml classification to `open-high` (or reclassify with an accurate rationale) without changing code

**Approach:** Update the `publish-writer-events-db-write-degrade-open-medium` entry's severity/rationale to accurately describe the risk (permanent data loss, not staleness), matching K8's actual four-branch framework result once the dead backstop is accounted for.

**Pros:** Fast, honest, unblocks accurate prioritization for a future fix-now unit.
**Cons:** Doesn't fix the underlying reliability gap.
**Effort:** 30 minutes.
**Risk:** Low.

### Option 2: Fix the underlying swallow — surface the write failure so the publish call site can retry or alert, rather than silently dropping it

**Approach:** Change `events/publish_writer.py`'s failure handling to propagate (or at least durably log/alert on) a write failure instead of "log and return None".

**Pros:** Actually closes the data-loss risk.
**Cons:** Changes an established fail-soft contract ("Errors are logged but never raised so a DB failure can't break a publish run") — needs careful design to avoid breaking the publish flow's own reliability guarantee in the other direction (a DB hiccup shouldn't now fail user-facing publishes). This is a genuine design tradeoff, not a mechanical fix.
**Effort:** 1-2 days (design + implementation + tests covering both the "publish still succeeds" and "operator is alerted to the gap" requirements).
**Risk:** Medium-high — touches a load-bearing reliability contract.

## Recommended Action

**To be filled during triage.** At minimum, apply Option 1 immediately (the registry entry should not misrepresent the actual risk). Option 2 should be scoped as its own follow-up unit/plan given the design tradeoffs involved.

## Technical Details

**Affected files:**
- `debt_registry.toml` — `publish-writer-events-db-write-degrade-open-medium` entry
- `src/backlink_publisher/events/publish_writer.py:67,206,212` — the three swallow sites
- `webui_app/helpers/history.py` — confirms no JSON backstop exists
- `src/backlink_publisher/_util/history_write.py` — the dead-code function that would have provided the backstop
- `src/backlink_publisher/events/reconcile.py::project_on_read` — confirmed does not re-derive from the missing backstop

## Resources

- Discovered by: `ce-code-review mode:autofix` run `20260706-140906-a92c9d99` (reliability reviewer), 2026-07-06.
- Related plan: `docs/plans/2026-07-06-002-opt-hidden-debt-hardening-sweep-plan.md` (Sprint D, Unit D3).

## Acceptance Criteria

- [ ] `debt_registry.toml`'s rationale for this entry accurately reflects that no independent backstop currently exists.
- [ ] Severity/status reclassified per an honest re-application of the plan's K8 four-branch framework.
- [ ] If Option 2 is pursued: a design decision is made and documented for how publish-flow reliability and data-loss-avoidance are both satisfied; tests cover both.

## Work Log

### 2026-07-06 - Initial Discovery

**By:** Claude Code (ce-code-review reliability persona, orchestrator synthesis + independent verification)

**Actions:**
- Verified `webui_app/helpers/history.py`'s docstring claim directly.
- Confirmed `append_published_rows` has zero non-test callers via grep.
- Read `project_on_read`'s actual implementation to confirm it re-derives from `EventStore`, not the claimed JSON backstop.

**Learnings:**
- Debt-registry classifications that cite "an independent recheck exists" must be verified against current code at classification time, not assumed from historical context (the backstop existed under an earlier plan, U2 removed it, and the registry entry wasn't updated to reflect that).

---

## Notes

- This entry was added in this very diff (D3) — it is not a pre-existing debt item, so correcting it now is squarely in scope for this review cycle.
