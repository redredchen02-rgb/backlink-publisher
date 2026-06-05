---
title: Three-Gap live_dofollow Under-Counting in Equity Ledger
date: 2026-06-05
category: docs/solutions/logic-errors
module: ledger_recheck_pipeline
problem_type: logic_error
component: service_object
severity: high
symptoms:
  - equity ledger reported live_dofollow=0 even with ~73 verified live-dofollow links in events.db
  - keepalive recheck probes ran successfully but liveness never surfaced in the ledger
  - publish.unverified articles never transitioned to confirmed state via recheck scheduling
  - platforms with uncertain dofollow_status contributed 0 to live_dofollow regardless of probe outcome
root_cause: logic_error
resolution_type: code_fix
tags:
  - live-dofollow
  - equity-ledger
  - recheck
  - verified-at
  - uncertain-platform
  - writeback
  - candidate-pool
  - logic-error
related_components:
  - background_job
  - database
---

# Three-Gap `live_dofollow` Under-Counting in Equity Ledger

## Problem

Three independent logic gaps compounded to make `live_dofollow` systematically under-counted in the equity ledger: probed-alive links never had `verified_at` written back to the database, half of unverified published articles were excluded from recheck scheduling, and probe confirmations for ~16 "uncertain" platforms were silently discarded instead of being promoted to dofollow.

## Symptoms

- `live_dofollow` count remained at 0 (or near-0) in the equity ledger even after successful keepalive probes had confirmed links were alive with no `rel=nofollow`.
- Links successfully probed showed as `unverified` in the ledger indefinitely — `articles.verified_at` was never updated.
- Articles on the `publish.unverified` path were never scheduled for recheck, blocking any path to confirmed status.
- Platforms with `dofollow_status() == "uncertain"` (approximately 16 platforms) contributed 0 to `live_dofollow` regardless of probe outcome.

## What Didn't Work

**Initial integration test design**: `test_run_recheck_alive_makes_ledger_live` assumed `build_ledger` would reflect the `articles.verified_at` DB write. In test mode, `build_ledger` reads liveness from the injected `history=` JSON, not from `articles.verified_at` in SQLite — the DB write was correct but invisible to the test path. Fix: split into two tests — one querying the DB table directly, one injecting `history=[{..., "verified_at": ts}]` into `build_ledger`.

**Importing helpers from test files**: Tried `from tests.test_recheck_selection import <helper>` — `tests/` is not a package (`ModuleNotFoundError`). Fix: inline all shared helpers in the test file that needs them.

**Naive/aware datetime subtraction**: `_parse_ts()` returns tz-aware datetimes; `datetime.now()` is naive, causing `TypeError: can't subtract offset-naive and offset-aware datetimes` in `select_unverified_candidates`. Fix: normalize at the function boundary with `now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)`.

**`build_ledger` store resolution order**: Calling `_load_confirmed_dofollow_urls(store)` before resolving `store` left it `None`. `build_target_buckets(store=None)` resolves store internally but does not reassign the caller's variable. Fix: `store = store or EventStore()` must be the first line of `build_ledger`.

## Solution

### Gap 1 — Write `verified_at` back on alive probe results

**`src/backlink_publisher/recheck/events_io.py`** — new `write_verified_at`:

```python
def write_verified_at(store: "EventStore", results: list[dict]) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    updated = 0
    with store.connect() as conn:
        for r in results:
            if r.get("verdict") != verdicts.ALIVE:
                continue
            article_id = r.get("article_id")
            if article_id is None:
                continue
            conn.execute(
                "UPDATE articles SET verified_at = ?, verify_error = NULL"
                " WHERE article_id = ?",
                (now, int(article_id)),
            )
            updated += 1
    return updated
```

Also extend the `emit_recheck` payload to carry probe signals forward for Gap 3:

```python
"confirmed_dofollow": bool(r.get("confirmed_dofollow", False)),
"confirmed_nofollow": bool(r.get("confirmed_nofollow", False)),
```

**`webui_app/services/keepalive_job.py`** — call `write_verified_at` after each probe and merge unverified candidates into the recheck pool:

```python
# After emit_recheck:
try:
    write_verified_at(store, [result])
except Exception:
    pass

# Pool construction (in _run_recheck when candidates is None):
confirmed = _default_candidates(store)
unverified = _default_unverified_candidates(store)
candidates = confirmed + unverified
```

### Gap 2 — Include `publish.unverified` articles in recheck scheduling

**`src/backlink_publisher/recheck/selection.py`** — added `_unverified_universe` and `select_unverified_candidates`:

```python
def _unverified_universe(store, *, since, host, run_id) -> dict[int, dict]:
    # Query PUBLISH_UNVERIFIED events
    # For NULL article_id rows: fallback join via live_url
    live_url_to_aid: dict[str, int] = {}
    for row in store.query(
        "SELECT article_id, live_url FROM articles WHERE live_url IS NOT NULL"
    ):
        live_url_to_aid[row["live_url"]] = row["article_id"]
    # ... article_id = live_url_to_aid.get(live_url) where NULL

def select_unverified_candidates(store, *, now, cap=20, min_retry_days=7, ...):
    now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    # Eligibility: last_attempt_at is None OR > min_retry_days ago
    # No days/last_definitive_at gate (unlike confirmed path — unverified
    # articles have no prior definitive recheck, only the retry floor applies)
```

The fallback join is required because the publisher write path does not wire `article_id` until the projector runs. Production SQL audit: 22/44 (50%) of `publish.unverified` events had `article_id=NULL`.

### Gap 3 — Propagate uncertain-platform probe signals to the ledger

**`src/backlink_publisher/recheck/probe.py`** — emit `confirmed_dofollow` / `confirmed_nofollow` for uncertain platforms:

```python
if res.get("target_is_nofollow"):
    if (dofollow_status(platform) if platform else None) is True:
        out["verdict"] = verdicts.DOFOLLOW_LOST
        out["reason"] = "rel_nofollow"
        return out
    out["expected_nofollow"] = True
    if platform and dofollow_status(platform) == "uncertain":
        out["confirmed_nofollow"] = True
else:
    # target_anchor_found AND NOT target_is_nofollow
    # Liveness-only probes return early at `if not target` — execution
    # cannot reach here without target_anchor_found, no extra guard needed.
    if platform and dofollow_status(platform) == "uncertain":
        out["confirmed_dofollow"] = True
out["verdict"] = verdicts.ALIVE
```

**`src/backlink_publisher/ledger/aggregate.py`** — read confirmed signals and resolve them in `_classify`:

```python
def _load_confirmed_dofollow_urls(store) -> frozenset:
    # Reads LINK_RECHECKED events with confirmed_dofollow=True
    # Uses canonicalize_url + (ts_utc, event_id) recency tiebreaker
    # Returns frozenset of canonical live_urls

def _classify(platform, *, confirmed_dofollow_urls=frozenset(), live_url=None):
    # ...
    if status == "uncertain":
        if live_url and live_url in confirmed_dofollow_urls:
            return "dofollow", None  # probe confirmed: no nofollow attr found
        return "uncertain", None
```

## Why This Works

**Gap 1**: `build_ledger` determines liveness through `history_query.list_history()`, which reads `articles.verified_at`. The keepalive job was probing correctly and emitting events, but never writing to the `articles` row. Without `UPDATE articles SET verified_at = ?`, the ledger always saw `NULL` and classified links as unverified. `write_verified_at` closes the loop.

**Gap 2**: `_confirmed_universe()` selected only `publish.confirmed` events. Any article on the `publish.unverified` path was invisible to the scheduler — it could never be promoted via recheck because it was never queued. The fallback `live_url → article_id` join is necessary because the publisher writes the event before the projector assigns `article_id`; without it, half the unverified pool silently drops on NULL.

**Gap 3**: `dofollow_status()` returns `"uncertain"` for platforms where the canonical link attribute is not statically known. Previously `_classify` treated `"uncertain"` the same as `"nofollow"` for ledger purposes — 0 contribution to `live_dofollow`. The probe already detected whether `rel=nofollow` was present; the signal just wasn't stored or read. By emitting `confirmed_dofollow` in the event payload and reading it in `_load_confirmed_dofollow_urls`, the ledger can use runtime evidence to resolve what static metadata cannot.

**Why they compound**: Even if Gap 3 had been fixed alone, articles wouldn't reach `verified_at` (Gap 1) and unverified articles would never be rechecked to generate the signal (Gap 2). All three must be fixed together to observe the improvement.

## Prevention

1. **Write-back completeness in probe jobs**: Any job that runs probes and emits events should assert in tests that the relevant DB column (e.g. `articles.verified_at`) is updated — not just that an event was emitted. Event emission and DB writeback are separate I/O paths; testing only one is insufficient.

2. **Recheck pool coverage test**: Create one `publish.confirmed` and one `publish.unverified` article, run the scheduler, and assert both appear in the candidate list. This would have caught Gap 2 at introduction.

3. **Uncertain-platform signal round-trip test**: For each platform in the `uncertain` tier, add a probe test asserting `confirmed_dofollow=True` appears in the emitted event when the probe finds no `rel=nofollow`. The ledger aggregate test should assert the URL appears in `_load_confirmed_dofollow_urls`.

4. **Avoid bare `datetime.now()` in functions that receive tz-aware inputs**: Normalize at the function boundary: `now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)`. Alternatively, define a `_now_utc()` helper that always returns tz-aware.

5. **`build_ledger` store resolution must be the first line**: Any refactor adding a pre-`build_target_buckets` call using `store` must ensure `store = store or EventStore()` is first. `build_target_buckets(store=None)` resolves store internally but does not reassign the caller's variable.

6. **Test-mode vs production-mode `build_ledger` liveness path**: In test mode `build_ledger` reads liveness from injected `history=` JSON, NOT from `articles.verified_at`. Tests of DB writeback must query SQLite directly — routing through `build_ledger` will not observe a DB-layer side effect.

## Related Issues

- `docs/solutions/integration-issues/dofollow-canary-verdict-dropped-at-publish-output-seam-2026-05-25.md` — "output-seam twin": a dofollow signal computed correctly but silently lost at the serialization boundary; same failure mode as Gap 3 from a different entry point
- `docs/solutions/logic-errors/projector-silent-drop-status-vocabulary-drift-2026-05-26.md` — "input-seam twin": events.db projector had a silent `else` branch dropping unrecognized records; structurally identical to Gap 2 (unverified events excluded from an authoritative consumer)
- `docs/solutions/architecture-patterns/server-side-gap-computation-2026-06-05.md` — downstream consumer of `live_dofollow` counts; the data displayed there was subject to systematic under-counting by these three gaps before this fix
