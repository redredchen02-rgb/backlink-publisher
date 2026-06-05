---
title: "LITE Release Accepted Deferrals — R7/R8/R10 (plan 010 Unit 5)"
date: 2026-06-05
category: architecture-patterns
module: backlink_publisher
problem_type: architecture_decision
component: release_readiness
severity: low
applies_when:
  - When reviewing whether LITE release deferred items are true blockers
  - When deciding whether to open new plans for G5b, Pydantic opt-in, or recheck timeout
tags:
  - lite-release
  - accepted-deferral
  - release-readiness
---

## Context

Plan 010 converged five residual risks before LITE release.  Three items were
intentionally deferred after code-verified review: G5b (cross-process
restart-durable rehydrate), Pydantic opt-in, and recheck timeout.  They are
recorded here so they leave the active backlog and are not reopened without a
concrete trigger.

---

## R7 — G5b: cross-process restart-durable rehydrate

**Status: accepted deferral**

G5a (same-process tab reopen) is implemented and regression-tested
(`tests/test_webui_keepalive_g5a_rehydrate.py`).  G5b (resuming a recheck job
after a full process restart) is deferred.

**Rationale:** LITE is a single-operator setup.  The operator is in the room
when rechecks run; a restart does not leave orphaned work with no oversight.
Process-restart durability requires either persisting job state to the DB or
a coordinator service — both are net-new architecture that exceeds the LITE
scope.

**Resume trigger:** An unattended/scheduled recheck is introduced (e.g., the
launchd job from R4 is extended to multi-hour runs without operator presence).
At that point, G5b becomes a reliability requirement.

---

## R10 — recheck timeout

**Status: accepted deferral**

The `recheck-backlinks` CLI has no per-probe or per-run wall-clock timeout.
A stuck probe blocks the run indefinitely.

**Rationale:** LITE runs are operator-initiated and short (the `--limit 200`
cap from R4 bounds the window).  The operator can Ctrl-C a stuck run.  A
timeout guard is desirable but not a release blocker.

**Resume trigger:** Unattended/scheduled recheck is introduced, or a probe is
observed hanging in production longer than the launchd `StartCalendarInterval`
window.  At that point, add a per-probe `socket.settimeout` or `signal.alarm`
and an overall run-wall-clock cap.

---

## R8 — Pydantic opt-in

**Status: accepted deferral, with security boundary noted**

`schema.py` dict validators are the **authoritative** safety boundary for
publish payloads (SSRF, injection, field format).  Pydantic type hints in
model files are non-authoritative documentation aids only.  There is no plan
to make Pydantic the enforcement layer.

**Rationale:** Migrating all payload validation to Pydantic v2 is a
cross-cutting refactor that would touch every adapter, every test fixture, and
the CLI pipeline.  The current `schema.py` layer is well-tested and covers the
security surface.

**Security boundary (important):** Any new route or feature that surfaces a
publish-payload field to the UI (e.g., R2c.a strip aggregation) must confirm
that the field is already validated at write-time by `schema.py` before
rendering it.  Do not assume Pydantic annotations on the model provide runtime
protection.

**Resume trigger:** (a) Third observed drift between Pydantic annotations and
`schema.py` validators; (b) any new field that carries SSRF-relevant or
injection-relevant content is added to a publish payload; (c) any new
read-path surfaces a payload field to the UI without a `schema.py` write-time
gate.

---

## R5 — webui.db same-key lost-update (conditional)

**Status: documented limitation, release-acceptable**

`tests/test_webui_store_concurrency.py::test_same_key_rmw_counter` quantified
the cross-process lost-update: ~44/100 RMW increments are lost under maximum
contention.  `webui_store` uses `RLock` for intra-process safety only; the
cross-process path has no flock.

**Security impact:** `webui.db` stores UI state (job snapshots, draft queue,
schedule config, history display state).  It does NOT store CSRF tokens,
session secrets, or throttle counters — those live in Flask session / memory.
Lost updates mean stale display state, not a security or data-integrity
violation.

**Release decision:** Acceptable for LITE (single operator, single process at
runtime).  The multi-process case (scheduler + WebUI simultaneously writing the
same key) is rare and only affects display staleness, not correctness.

**Resume trigger:** A second persistent process that writes `webui.db` is
introduced (e.g., the launchd recheck job and the WebUI both updating the same
history-display key).  At that point, add `fcntl.flock` across the full RMW in
`sqlite_base.py`, consistent with `circuit.py`'s cross-process flock pattern.
