---
date: 2026-06-09
topic: v040-operator-autonomy
---

# v0.4.0 — Operator Autonomy

## Problem Frame

0.3.1 delivered the core keep-alive loop and SQLite store migration. The pipeline now
*can* execute end-to-end, but every operation still requires heavy operator involvement:
publishing to multiple targets means clicking through each one, keep-alive maintenance
means watching for failures and manually re-queuing each row, batch cross-target work
requires repeating the same steps N times, and credential expiry is only discovered at
publish-failure time rather than proactively.

The operator's job should be to express intent once — "keep these 10 targets alive on
these platforms" — and let the system handle the repetitive execution loop. 0.4.0
closes the gap between "the pipeline runs" and "the pipeline runs itself."

Three secondary axes are included because they're prerequisites for the automation
features: observability (operators need signals to trust automation), test infrastructure
(CI must be confident before shipping autonomous behaviors), and a health endpoint
(monitoring hooks into automation).

```
Operator Autonomy =  fewer clicks  +  proactive alerts  +  trusted CI
```

## Requirements

**Autopilot Scheduling**

- R1. The WebUI exposes a per-target autopilot toggle. When enabled, the system
  schedules recurring keep-alive cycles (recheck → gap detection → republish → verify)
  on a configurable interval (daily / weekly / custom cron). Operators do not need to
  initiate keep-alive manually.
- R2. Autopilot cycle outcomes are written to the history store with a distinct
  `source: autopilot` marker, so manual and automated runs are visually separated in
  the history panel.
- R3. If a keep-alive cycle ends with unresolved failures (republish failed, recheck
  still dead), the system surfaces a persistent banner or badge on the dashboard —
  autopilot does not silently swallow errors.
- R4. Autopilot can be paused globally (maintenance mode) without losing individual
  per-target configuration.

**Batch Target Operations**

- R5. The site list view adds a multi-select checkbox column. Selected targets can be
  submitted to a single batch operation: run keep-alive, force recheck, publish new
  content, or check channel health.
- R6. Batch operations execute in a queue with per-target progress visible in real time.
  Partial failures surface per-target, not as an all-or-nothing result.
- R7. Batch recheck respects existing platform throttle settings and does not collapse
  all requests to simultaneously.

**Channel Health and Proactive Binding**

- R8. The settings channel cards show a credential TTL estimate where inferable (e.g.
  OAuth token expiry, last-seen binding age). Credentials within 7 days of expected
  expiry are highlighted before a publish failure occurs.
- R9. A "Test binding" action on each channel card performs a lightweight liveness probe
  (e.g. a minimal authenticated API call) without publishing, and reports
  `alive` / `expired` / `unreachable` inline.
- R10. When an `AuthExpiredError` fires at publish time, the error card in the history
  view includes a one-click "Re-bind now" shortcut that opens the binding modal for
  the affected channel — operators do not need to navigate to settings manually.
- R11. Credential age is recorded in `channel-status.json` at every successful binding
  so R8 TTL estimates have a base timestamp.

**Streamlined Publish Workflow**

- R12. The "Publish new content" flow persists the last-used platform selection and
  target set to `webui_store` (not session memory), so defaults survive page refresh
  and browser restart.
- R13. A quick-publish button on the site detail page (or site list row) initiates a
  publish run using the persisted defaults from R12 — zero configuration required for
  repeat operations. If no defaults exist yet, the button opens the full flow.
- R14. The publish progress overlay shows real-time per-platform status without
  requiring the operator to navigate to a separate page.

**Observability: Health Endpoint**

- R15. `GET /health` (or `/api/health`) returns a JSON payload with: WebUI liveness,
  last successful pipeline run timestamp, APScheduler status, and channel binding
  statuses. Exits with `200` when healthy, `503` when degraded.
- R16. The health endpoint is accessible without a CSRF token (read-only) but is still
  loopback-gated unless `BACKLINK_PUBLISHER_ALLOW_NETWORK=1`.
- R17. The dashboard homepage displays a health summary card driven by the same data
  as R15, so operators see system state without querying the endpoint directly.

**Test Infrastructure**

- R18. CI enforces a minimum coverage threshold of **80%** (current baseline: 83.2%,
  measured 2026-06-09). The floor is set at 80% to be immediately green on main while
  still preventing regressions. Configurable via `pyproject.toml`; raise incrementally.
- R19. At least the 10 highest-value test files are annotated with tier markers
  (`@pytest.mark.unit` / `@pytest.mark.integration`) so CI can run `unit` only on
  quick pushes.
- R20. `tests/test_webui_route_contract.py` (currently 1791 SLOC, 28 test classes) is split into
  per-concern files (`test_webui_auth_routes.py`, `test_webui_pipeline_routes.py`,
  etc.) with each under the 500-SLOC guidance threshold.

## Success Criteria

- An operator can configure autopilot for all active targets in under 2 minutes and
  then not need to touch the WebUI for a normal maintenance week.
- Credential expiry is surfaced before it causes a publish failure at least 80% of the
  time across tested OAuth-based adapters (token-paste adapters have no expiry signal
  and are explicitly out of scope for this criterion).
- Batch keep-alive for 10 targets completes via a single operator action.
- `/health` returns a useful response within 500 ms under normal load.
- CI coverage gate is active and enforced on merge before v0.4.0 ships (the gate
  blocking a real regression is a trailing indicator; the shipping gate is simply
  "gate exists and is green on main").

## Scope Boundaries

- **No new platform adapters in this release.** The Telegraph Phase 0 outcomes (G1
  index rate, G2 dofollow retention at T+21) are still pending. dev.to / hashnode
  evaluation is in `_drafts/platform-switch-evaluation-followup.md` and remains
  conditional on those outcomes. Platform expansion is 0.4.1 or a separate release.
- **No RECON schema formalization in this release.** The `no-recon-schema` debt item
  (medium severity) is real but designing a typed taxonomy is its own work item;
  including it here would bloat scope. Log it as a `0.5.0` candidate.
- **No full CODEOWNERS / stewardship tooling.** The `no-stewardship-model` debt item
  is low severity for a solo/small team and won't block the primary goals here.
- **No dead code / orphan-code audit.** The `orphan-code-unknown` debt item requires a
  dedicated sweep, not one-off fixes.
- **Autopilot does not make publish decisions.** It runs configured intent — it does
  not choose new targets, write new content, or select platforms autonomously.

## Key Decisions

- **R1 uses APScheduler (already in webui_app)** rather than an external cron daemon:
  keeps the "double-click to run" operator model intact, no new infrastructure.
- **R8 TTL estimate is best-effort, not guaranteed**: credential lifetimes vary by
  platform and many provide no expiry signal. The estimate is surfaced as a heuristic,
  not a hard guarantee.
- **R18–R20 are CI debt clearance, not autonomy features**: they do not directly
  reduce operator clicks, but they are prerequisite for shipping autonomous behaviors
  with confidence. They are included here rather than deferred to avoid a "always
  block 0.5.0" pattern. If scope pressure hits, R19–R20 are the first cuts.
- **R18 coverage gate starts at 60%**: current suite coverage is unmeasured. Starting
  at 60% is realistic without a big initial investment; it can be raised incrementally.
- **R5 batch via queue, not parallel dispatch**: avoids throttle collisions and gives
  per-target observability. Sequential execution with platform-aware delays.

## Dependencies / Assumptions

- APScheduler is already initialized in `webui_app/create_app()` and excluded from
  pytest — R1/R4 can extend existing infrastructure.
- `webui_store/channel_status` already records binding timestamps — R11 is an
  extension, not a new store.
- The existing `/ce:keep-alive` flow (S1-S7) is the execution primitive that R5/R6
  batch over — it does not need to be rewritten.

## Outstanding Questions

### Resolve Before Planning

*All blocking questions resolved — ready for `/ce:plan`.*

- ~~[Affects R18] Coverage baseline~~ **RESOLVED 2026-06-09**: 83.2% measured.
  R18 floor set to 80% (green on main, prevents regressions). Note: 34 pre-existing
  test failures in `test_cli_weights`, `test_cli_show_optimization_state`,
  `test_collect_signals`, `test_optimization_*` — these are pre-0.4.0 regressions from
  the `weights` CLI consolidation and should be fixed before the coverage gate lands.
- ~~[Affects R1] APScheduler job persistence~~ **RESOLVED 2026-06-09**: Scheduler uses
  in-memory store intentionally. Intent persists in SQLite stores; `_restore_scheduled_jobs()`
  re-registers on startup (confirmed in `webui_app/scheduler.py`). R1 autopilot follows
  the same pattern — no migration needed.

### Deferred to Planning

- [Affects R8][Technical] Which OAuth adapters expose a reliable credential expiry
  signal (`expires_at`, refresh timestamp)? Enumerate them to set realistic scope for
  the TTL heuristic UI.
- [Affects R20][Needs research] What is the right split boundary for
  `test_webui_route_contract.py`? Read the file to identify which test classes map
  to which concern groupings before proposing split files.

## Next Steps

→ All blocking questions resolved. Ready for `/ce:plan`.

**Pre-flight note**: 34 pre-existing test failures (`test_cli_weights`, `test_cli_show_optimization_state`, `test_collect_signals`, `test_optimization_*`) should be fixed before the R18 coverage gate ships — these are likely old CLI entry-point regressions from the `weights` consolidation in 0.3.1.
