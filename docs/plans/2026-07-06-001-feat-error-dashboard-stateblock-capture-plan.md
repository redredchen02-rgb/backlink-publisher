---
title: "feat: Capture StateBlock gracefully-handled errors in the error-reporting dashboard"
type: feat
status: parked
parked: "2026-07-06 — holds a real finding (StateBlock-rendered errors are invisible to the error-reporting dashboard) but has no implementation units yet. Resume trigger: pick this up once docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md's U14/U15 error-audit units land, or whenever someone is ready to design the capture-hook approach in Open Questions below."
date: 2026-07-06
origin: docs/audits/2026-07-03-webui-feature-error-backlog.md
claims: {}
---

# feat: Capture StateBlock gracefully-handled errors in the error-reporting dashboard

## Overview

The error-reporting dashboard shipped by `docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md` (completed) only captures *unexpected* exceptions: `window.onerror`, unhandled promise rejections, the Vue `errorHandler`, `router.onError`, vue-query cache errors, and Pinia `$onAction` failures. It never sees errors that are *gracefully handled* — i.e. an API response correctly classified as an error and rendered through `StateBlock`'s error state, or a legacy-page warning banner. Those are normal, controlled code paths, not exceptions, so none of the five capture hooks ever fire for them.

## Problem Frame

During U14 (read-only error-audit unit of `docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md`), a full two-round walkthrough (curl scan + live browser walkthrough of all 22 legacy/SPA URLs) found two real, user-visible error states (the `/app/pr-queue` LITE-mode generic-error screen, and the homepage "system degraded" banner) — yet `GET /api/v1/error-reports` returned `{"items": [], "total": 0}` throughout, before and after. The dashboard's entire value proposition — turning "features error normally but nobody notices" into a visible, prioritizable backlog — silently fails for exactly the class of error a user is most likely to actually see, because "gracefully handled" and "invisible to monitoring" currently mean the same thing.

This is a structural gap in the completed 2026-07-01-002 plan, not something introduced by this session's work. Full write-up: `docs/audits/2026-07-03-webui-feature-error-backlog.md`, "發現 #4".

## Scope Boundaries

- Explicitly out of scope for `docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md`'s U14/U15 (K: "不重建或修改該儀表板本身的擷取/儲存/呈現邏輯" — U14/U15 consume the dashboard's existing API, they don't modify its capture/storage/presentation logic).
- This plan is parked, not active — no implementation units are defined yet. It exists to hold the finding so it isn't lost, not to commit to an approach.

## Open Questions (to resolve when this plan is picked up)

- Where should the capture hook live? Candidates: a `StateBlock`-level prop/emit that fires a report when it renders its `error` variant (SPA-only); a legacy-page equivalent for the Jinja/vanilla-JS pages that still render warning banners (`static/js/index.js` and friends); or a lower-level hook in the shared API client (`frontend/src/api/client.ts`) that reports whenever a response is classified as an error, regardless of which component ends up rendering it.
- Should *every* StateBlock error render generate a report, or only ones above some visibility/frequency threshold? Naively capturing every render risks flooding the dashboard with expected, momentary states (e.g. a component re-fetching after a user action).
- Does this need de-duplication logic beyond what `ErrorReportStore.find_by_fingerprint`/`increment_occurrence` already does, given these reports will fire on every render of an already-known, persistent condition (e.g. the B2 banner) rather than once per incident?
- Interaction with whatever B2 resolution ships first: if B2 changes the "never published" banner to a non-alarming, non-degraded presentation, does that state still warrant a dashboard report at all?

## Sources & References

- Origin finding: `docs/audits/2026-07-03-webui-feature-error-backlog.md`, 發現 #4
- Existing dashboard: `docs/plans/2026-07-01-002-feat-frontend-error-reporting-plan.md` (completed), `webui_store/error_reports.py`, `webui_app/api/v1/error_reports.py`, `frontend/src/pages/ErrorReports/`
- Parent plan: `docs/plans/2026-07-02-001-opt-v060-uiux-pipeline-upgrade-plan.md` (U14/U15)
