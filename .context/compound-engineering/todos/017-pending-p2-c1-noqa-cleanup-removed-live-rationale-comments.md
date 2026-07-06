---
status: pending
priority: p2
issue_id: "017"
tags: [maintainability, documentation, hardening-sweep]
dependencies: []
---

# C1's dead-noqa cleanup removed trailing rationale text (not just the noqa directive) for ~400 except-Exception sites outside D2/D3's classification scope

## Problem Statement

C1 (`4bf8b70f`) removed 340 dead `# noqa` comments across 131 files via `ruff check --extend-select RUF100 --fix --fixable RUF100`. The maintainability code-review pass found that over half of the 218 removed `# noqa: BLE001` comments carried trailing rationale text (e.g. `— never 500 the page`, `— fail-continue per plan`) documenting *why* a broad `except Exception` was intentional at that site. D2/D3 later reintroduced this kind of documentation as `# debt: <slug>` + `debt_registry.toml` entries, but only for `publishing/adapters/` (D2) and `cli/_bind/`+`events/` (D3) — roughly 102 of the repo's ~502 current `except Exception` sites. Files outside that scope (e.g. `webui_app/routes/health.py` — 23 lost annotations, `health_metrics.py` — 9, `webui_app/__init__.py` — 7, `keepalive/chain.py`, `content/scraper.py`, and others) now have bare `except Exception` blocks with zero registry coverage and zero inline explanation, recoverable only via `git blame`.

## Findings

- Spot-checked ~12 files across different rule codes during C1's own review — confirmed no logic/import changes, only comment text removed (this is not a correctness bug).
- The removed comments frequently carried more than a bare `# noqa: BLE001` — many had appended prose explaining the site's safety rationale, which is now gone from the source (though still recoverable via `git blame`/`git log` on the removed lines).
- The plan's own D2/D3 execution notes verify "no lint-signal change" (true) but do not address this documentation-loss dimension.
- This is a genuine, if modest, regression in in-context documentation for a class of sites this exact hardening-sweep plan cares about (except-Exception hygiene) — ironic given the plan's own stated purpose.

## Proposed Solutions

### Option 1: Extend the D2/D3 classification methodology (K8 four-branch framework + debt_registry.toml clustering) to the remaining ~400 sites in a dedicated follow-up unit/plan

**Pros:** Closes the documentation gap comprehensively and consistently with the established pattern.
**Cons:** Significant scope — this is essentially "D4/D5" of the same plan family.
**Effort:** Multi-day (comparable to D2+D3 combined, given the larger site count).
**Risk:** Low (methodology already proven twice).

### Option 2: Recover just the removed rationale text from git history (`git show <c1-commit>^:<file>` diffed against current) and re-attach it as plain comments (without the full debt_registry.toml formality) at the highest-traffic/highest-risk files first

**Pros:** Much cheaper than full K8 classification; restores lost context quickly.
**Cons:** Doesn't get the structured tracking/governance benefit of the debt_registry.toml approach.
**Effort:** 2-4 hours for the highest-count files (health.py, health_metrics.py, etc.).
**Risk:** Low.

## Recommended Action

**To be filled during triage.** Recommend scoping this as a proper follow-up plan (Option 1) given the plan's own precedent for batching this kind of work into separate, independently-mergeable units — this review flags it as a known gap, not something to patch reactively within this diff.

## Technical Details

**Affected files (highest-density, from the maintainability review's spot-check):** `webui_app/routes/health.py` (23), `webui_app/health_metrics.py` (9), `webui_app/__init__.py` (7), `src/backlink_publisher/keepalive/chain.py`, `src/backlink_publisher/content/scraper.py`, and others across the ~400 unclassified sites.

## Resources

- Discovered by: `ce-code-review mode:autofix` run `20260706-140906-a92c9d99` (maintainability reviewer), 2026-07-06.
- Related commits: `4bf8b70f` (C1, the removal), `a5f8ba3a`/`c104dd95` (D2/D3, the partial re-documentation via debt_registry.toml).

## Acceptance Criteria

- [ ] A decision is recorded on whether/when a D4-style follow-up classification sweep covers the remaining ~400 sites.
- [ ] If recovering comments piecemeal (Option 2): highest-density files get their rationale restored first.

## Work Log

### 2026-07-06 - Initial Discovery

**By:** Claude Code (ce-code-review maintainability persona)

**Actions:**
- Spot-checked ~12 files across rule codes to confirm no logic changes, only comment removal.
- Identified that a meaningful fraction of removed noqa comments carried rationale prose beyond the bare directive.

---

## Notes

- Not a correctness bug — purely a documentation/governance completeness gap. Ironic given this is itself the "hidden-debt hardening sweep" plan's exact concern area.
