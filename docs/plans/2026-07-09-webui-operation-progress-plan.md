---
title: "opt: Operation-progress visibility + UI usability (async task backend, task center, unified status)"
type: opt
status: active
date: 2026-07-09
origin: user request — analyze codebase, iterate UX, make interface usable, surface operation progress
deepened: 2026-07-09
claims:
  # Restored 2026-07-13 after feat/operation-progress merged to origin/main.
  # Backend + components + tests only — router/nav/PublishWorkbench wiring is
  # still open (see plan body), so those files are not claimed yet. The
  # original claim of webui_app/routes/operations.py was drift: the endpoint
  # landed at webui_app/api/v1/operations.py.
  paths:
    - webui_store/operation_store.py
    - webui_app/services/operation_worker.py
    - webui_app/api/v1/operations.py
    - frontend/src/api/operations.ts
    - frontend/src/composables/useOperation.ts
    - frontend/src/stores/operations.ts
    - frontend/src/components/OperationProgress.vue
    - frontend/src/components/StatusBadge.vue
    - frontend/src/pages/Operations/OperationsPage.vue
    - tests/test_webui_operations_routes.py
    - tests/test_operation_store.py
    - tests/test_operation_worker.py
---

# opt: Operation-progress visibility + UI usability

## Problem

The primary `plan` / `validate` / `publish` flows in the WebUI run **synchronously
and block the HTTP request**; the publish route (`webui_app/routes/pipeline_publish.py`)
calls `PipelineAPI.publish(...)` and renders HTML directly. Browser-tier publishes can
block up to 300s (`sdk/_cli_runner.py`). No job id is returned and no progress signal
exists. On the SPA side, `PublishWorkbench.vue` + `stores/publish.ts` only flip three
boolean busy flags — the code itself admits it cannot tell "running" from "done" (the
45s soft-timeout copy). Navigating away discards all state, and notifications are
transient toasts only.

## Solution

Mirror the proven `CampaignWorker` + `CampaignSqliteStore` + polling-endpoint pattern
(a background `ThreadPoolExecutor` worker, a SQLite op store, a `GET /operations/<id>`
poll endpoint). Make the heavy publish / publish-chain flows asynchronous: submit
returns an `op_id` immediately, the worker runs the pipeline in a thread and persists
stage + progress %, and the SPA polls. Add a global task center (`/operations`) with a
nav badge, a reusable `OperationProgress` component, a unified `StatusBadge`, and
persistent notification history.

Constraints honored: polling only (SSE/WebSocket explicitly rejected in origin
requirements); reuse existing `PipelineAPI` + history helpers; do not edit `cli/*.py`
or `schema.py`; new `/api/v1/operations/*` endpoints registered in `spec.py` (Spectral /
oasdiff gate); mypy + ruff + monolith SLOC budgets; single-operator local tool.

## Acceptance

- Publish button releases immediately; step indicator + progress bar appear; user can
  switch pages and return to `/operations` to see the still-running task; completion /
  failure yields a persistent notification and a task record; in-flight task is
  cancelable.
- One-click chain (plan → validate → publish) shows three-stage progress; leaving the
  page does not lose state.
- `BatchCampaign` enters the SPA progress page (no longer jumps to legacy Jinja).
- Status badges unified across pages; no ruff / mypy / unit-test regressions; plan-check
  passes.

## Phases

- P0 plan doc + `plan-check`.
- P1 backend: `OperationSqliteStore` → `OperationWorker` → `routes/operations.py` →
  mount in `create_app` → register in `spec.py`.
- P2 frontend core: `api/operations.ts` + `useOperation` composable + `stores/operations.ts`
  + `OperationProgress.vue` + wire `PublishWorkbench`.
- P3 visibility: `/operations` page + nav badge + `StatusBadge` + fix `BatchCampaign` redirect.
- P4 polish: persistent notification history + consistent empty/loading states.
- P5 verify: backend + frontend unit tests, ruff, mypy, pytest `-m unit`, SLOC budgets,
  plan-check.
