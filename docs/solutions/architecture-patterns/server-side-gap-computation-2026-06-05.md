---
title: "Server-Side Gap Computation for Operational Dashboards"
date: 2026-06-05
category: architecture-patterns
module: webui_app
problem_type: architecture_pattern
component: development_workflow
severity: medium
applies_when:
  - When an admin page requires daily use and operators must mentally compute actionable insights from raw data
  - When the same derived data (e.g., missing platforms) is consumed by display, fill, and reporting features
  - When batch operations on many items benefit from async job tracking with status polling
  - When the server already holds all data needed for computation but the response only includes raw fields
  - When operators' primary workflow is identifying what's missing or broken across many targets
tags:
  - server-side-computation
  - gap-analysis
  - operational-dashboard
  - flask
  - batch-operations
  - async-job-polling
  - equity-ledger
  - dofollow-check
---

# Server-Side Gap Computation for Operational Dashboards

## Context

The Backlink Equity Ledger page displayed raw backlink data in English with no
operational affordances — no summary statistics, no visualization of which
dofollow platforms each target is missing, no way to fill gaps or batch-recheck
anchor attributes. Operators had to mentally compute the gap between current
dofollow coverage and the full set of active dofollow platforms for each target,
then manually run one-off CLI commands to fill missing platforms or recheck
stale anchors.

## Guidance

Four patterns work together. The core principle: **every judgment an operator
needs should be computed server-side and injected into the response, not left
for the operator to compute mentally.**

### Pattern A — Server-side gap computation

In the GET route handler, compute each target's missing dofollow platforms by
subtracting its `live_dofollow_platforms` from the set of all active dofollow
platforms. Use the publishing registry to determine which platforms are active:

```python
def _active_dofollow_platforms(self) -> list[str]:
    return [name for name in registered_platforms()
            if dofollow_status(name) == _DofollowStatus.DOFOLLOW]

def _compute_missing(self, row: dict) -> list[str]:
    active = set(self._active_dofollow_platforms())
    live = set(row.get("live_dofollow_platforms", []))
    return sorted(active - live)
```

Inject the result into each row's JSON bootstrap data:

```python
row["missing_dofollow_platforms"] = self._compute_missing(row)
```

This keeps the gap logic in Python where the registry already lives, avoids
shipping platform knowledge to the client, and makes the template and JS
simpler (just render what's given).

### Pattern B — In-process fill gaps

A POST endpoint that accepts target URLs, canonicalizes them, and calls the
plan-gap engine in-process — not via CLI subprocess:

```python
@app.route("/api/equity/fill-gaps", methods=["POST"])
def fill_gaps():
    urls = request.json.get("urls", [])
    canonicalized = [canonicalize_url(u) for u in urls]
    results = []
    for url in canonicalized:
        result = plan_gap_engine.compute_strategy(url, stale_days=7)
        results.append({"url": url, "filled": result})
    return jsonify(results)
```

In-process avoids subprocess overhead, error-handling complexity, and keeps
the response synchronous with the request lifecycle.

### Pattern C — Batch recheck with polling

A POST endpoint starts a background thread; a GET endpoint polls job status.
In-memory job store with a threading lock:

```python
_jobs: dict[str, dict] = {}
_lock = threading.Lock()

@app.route("/api/equity/batch-recheck", methods=["POST"])
def start_recheck():
    job_id = str(uuid4())
    urls = request.json.get("urls", [])
    with _lock:
        _jobs[job_id] = {"status": "running", "urls": urls}
    threading.Thread(target=_run_recheck, args=(job_id, urls)).start()
    return jsonify({"job_id": job_id})

@app.route("/api/equity/batch-recheck/<job_id>/status")
def poll_recheck(job_id):
    with _lock:
        job = _jobs.get(job_id, {"status": "not_found"})
    return jsonify(job)
```

The front-end polls every 2 seconds until `status == "done"`, then refreshes
the table. Same architecture as the existing keep-alive service.

### Pattern D — Chinese operational UI

The template was rewritten from English to Chinese, with:
- A summary stats bar (total targets, healthy count, attention-needed count)
- Preset filter chips (全部 / 需关注 / 全部弱 / 健康)
- A batch action bar with Fill Gaps and Batch Recheck buttons
- Platform badges with color-coded dofollow/nofollow/missing states
- Expandable detail rows showing gap visualization

The client-side JavaScript handles L10N strings, rendering, filtering, and
polling — no i18n framework needed for a single-page internal tool.

## Why This Matters

This set of patterns addresses the most common operational dashboard antipattern:
**UI displays raw data and outsources interpretation to humans.** The human
brain is poor at computing set differences between multiple collections in
real-time, especially when the set of active dofollow platforms changes as
the business adjusts its publishing strategy.

Server-side gap computation gives a **single source of truth**:
`_active_dofollow_platforms()` is defined once and shared across the display
route, the fill-gaps endpoint, and any future consumers. There is no risk of
the UI and CLI having different definitions of "active dofollow platform."

Batch operations (fill gaps + batch recheck) eliminate the open-terminal →
copy-URL → paste → wait → repeat loop. The background polling pattern is
simpler than WebSockets, needs no extra infrastructure for a lightweight
Flask app, and is already established in the codebase (keep-alive service).

## When to Apply

- The front-end displays data requiring mental computation (set differences,
  intersections, filters) before an operator can act.
- The same derived data is consumed by multiple features (display, fill,
  reporting) — compute it once server-side.
- The page's primary users are internal operators, not external customers —
  you can customize UI language and layout freely.
- Batch operations on multiple items are more frequent than single-item
  operations, and each operation takes an unpredictable amount of time.
- The server already has all the data needed for the computation — it just
  wasn't including it in the response.

## Examples

**Before** — raw data, operator must mentally compute the gap:

```python
# equity_ledger.py — GET route returns only raw fields
rows = [
    {
        "url": "https://example.com",
        "live_dofollow_platforms": ["linkedin", "twitter"],
    },
]
```

**After** — server injects the computed gap:

```python
# equity_ledger.py — same route, with gap computation
rows = [
    {
        "url": "https://example.com",
        "live_dofollow_platforms": ["linkedin", "twitter"],
        "missing_dofollow_platforms": ["facebook", "github", "medium"],
    },
]
```

The front-end renders missing platforms as red badges ("缺 facebook, github,
medium"). The operator sees the gap immediately and can click to trigger the
fill-gaps endpoint — no mental math, no CLI.

**Batch recheck flow:**

```
1. Operator selects targets → clicks "批量重查"
2. POST /batch-recheck → returns { job_id: "abc-123" }
3. Front-end polls GET /batch-recheck/abc-123/status every 2s
4. When status == "done", front-end refreshes the table
5. Operator sees updated dofollow status for all targets
```

## Related

- `best-practices/webui-config-request-cache-governance-2026-06-03.md` —
  covers the `_g_cache` pattern used in the same route layer
- `ux-honesty/webui-false-success-resolution.md` — Flask route error-handling
  patterns applicable to all WebUI endpoints
- `best-practices/standalone-page-vs-retrofit-webui-2026-05-15.md` — sibling
  page pattern for WebUI architecture decisions
