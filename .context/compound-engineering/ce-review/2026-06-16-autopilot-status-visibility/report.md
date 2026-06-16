# ce:review run — 2026-06-16-autopilot-status-visibility

**Mode:** autofix  
**Branch:** feat/autopilot-status-visibility  
**Base:** HEAD~1 (57e089b)  
**Plan:** docs/plans/2026-06-16-001-feat-autopilot-status-visibility-plan.md  
**Reviewers:** 8 (correctness, testing, maintainability, project-standards, kieran-python, julik-frontend-races, api-contract, reliability)

---

## Auto-fixes Applied

| File | Change | Reviewer |
|------|--------|----------|
| `webui_app/routes/sites.py:78` | Wrapped `get_job()` in try/except → `_job = None` on error. Prevents GET /sites returning 500 on APScheduler internal error. | reliability |

---

## Residual Findings

### P1 — Must fix before merge

**[1] Plan doc missing `claims:` block** · `project-standards` · confidence 0.95  
File: `docs/plans/2026-06-16-001-feat-autopilot-status-visibility-plan.md:1`  
All plans dated ≥ 2026-05-20 must carry `claims:` frontmatter. `plan-claims-gate` CI will block merge without it.  
**Fix:** Add to frontmatter:
```yaml
claims:
  paths:
    - webui_app/routes/sites.py
    - webui_app/templates/sites.html
    - webui_app/static/js/sites.js
    - webui_app/templates/health.html
    - tests/test_webui_sites_routes.py
```
Or use `claims: {}` explicit opt-out.  
Owner: **human** (needs commit SHA)

**[2] POST rollback overwrites concurrent updates to OTHER sites** · `correctness` · confidence 0.85  
File: `webui_app/routes/sites.py:328`  
`snapshot_targets` is taken at line 298 for the entire `autopilot_targets` dict. If rollback fires, all concurrent updates to other sites' configs are lost.  
**Fix:** Store only the per-site snapshot: `snapshot_site_cfg = dict(current_targets.get(site_url, {}))`. Rollback only that site.  
Owner: **human**

**[3] POST partial failure: scheduler job registered but store rolled back** · `reliability` · confidence 0.82  
File: `webui_app/routes/sites.py:305`  
If `get_job()` raises after `_register_autopilot_job()` succeeds, exception handler rolls back the store (autopilot=disabled) but leaves the APScheduler job running. Scheduler-store state mismatch.  
**Fix:** Wrap only `get_job()` in a nested try/except (don't trigger rollback). `next_run_time_iso = None` on exception is acceptable — job is registered, just not queryable yet.  
Owner: **human**

---

### P2 — Should fix

**[4] `isinstance(str)` guard on `isoformat()` is test-workaround in production** · `kieran-python` · confidence 0.85  
File: `webui_app/routes/sites.py:81,308`  
`datetime.isoformat()` always returns `str`. The guard exists because MagicMock returns MagicMock. The test fixture should configure `mock.next_run_time.isoformat.return_value = "2026-06-17T10:00:00+08:00"` instead.  
Owner: **human** (requires test fixture change)

**[5] Inconsistent scheduler access: GET uses `.get()`, POST uses `[]`** · `maintainability` · confidence 0.82  
File: `webui_app/routes/sites.py:70,301`  
GET: `_sys.modules.get('webui_app.scheduler')` (safe). POST: `_sys.modules['webui_app.scheduler']` (raises KeyError). Divergent behavior confuses maintainers.  
Owner: **human**

**[6] Function-level `import sys` and `import webui_store` hides dependencies** · `kieran-python + maintainability` · confidence 0.88  
File: `webui_app/routes/sites.py:66-67,300`  
Both repeated inside functions; hides from static analysis. Move to module-level if no circular import concern.  
Owner: **human** (verify no circular import before moving)

**[7] `formatRelative()` has no unit tests** · `testing` · confidence 0.92  
File: `webui_app/static/js/sites.js:5`  
4 logic branches (null, past, <1h, <24h, ≥24h), none tested. Consider adding `tests/js/test_sites.mjs`.  
Owner: **human**

**[8] `sites.html` Jinja conditionals not HTML-content tested** · `testing` · confidence 0.88  
`TestSitesAutopilotStatus` only checks HTTP 200, not rendered HTML. `alert_pending` and `next_run_time_iso` branches are untested for output.  
Owner: **human** (test client config limitation)

**[9] Stale `statusCell` DOM reference across await** · `julik-frontend-races` · confidence 0.82  
File: `webui_app/static/js/sites.js:159`  
`statusCell` resolved before `await postJson()`. If Turbo frame swaps during request, subsequent `.textContent` writes hit detached node.  
**Fix:** Check `statusCell?.isConnected` before writing. Pre-existing pattern, low urgency for non-Turbo context.  
Owner: **human**

---

### P3 — Advisory

- `health.html` badge count not tested for multiple alerts — testing
- `get_job()` in POST still unguarded after register (the safe_auto above covers GET; POST version is guarded by the outer try/except but causes incorrect rollback behavior — see finding [3])
- Naming: `_sched_mod`, `_ws` with underscore prefix on local variables is non-idiomatic — maintainability

---

## Coverage

| Reviewer | Findings | Notes |
|----------|----------|-------|
| correctness | 1 confirmed P1 | |
| testing | 4 findings | |
| maintainability | 3 findings | |
| project-standards | 1 P1 | claims block |
| kieran-python | 4 findings | 2 overlap with maintainability |
| julik-frontend-races | 2 findings | 1 pre-existing pattern |
| api-contract | 0 | additive change, safe |
| reliability | 2 P1 (1 auto-fixed), 1 P2 | |

---

## Downstream Actionable Work

1. Add `claims:` to plan frontmatter (needed for CI gate)
2. Fix snapshot-rollback to be per-site only (P1 correctness)
3. Guard `get_job()` in POST with nested try/except, not triggering rollback (P1 reliability)
4. Update test fixture to configure `isoformat.return_value` string; remove `isinstance` guards from production code (P2 gated)
