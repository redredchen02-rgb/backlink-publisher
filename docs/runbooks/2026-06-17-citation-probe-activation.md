# Runbook — citation-probe activation verification

Phase 0 U2 (plan `docs/plans/2026-06-17-002-feat-activation-verify-gate-plan.md`).

**Purpose:** the *one-time, real (non-mock) live run* that proves `probe-citations`
actually writes `citation.observed` rows to events.db against the live Perplexity
API. The mock tests (`tests/test_cli_probe_citations.py::test_probe_writes_citation_rows_with_floor_fields`)
prove the wiring; **this runbook proves the live seam**.

> **Phase 0 status:** citation is verified at the **mock + runbook** level only.
> The real live run below is gated on the Perplexity v1 quota (below) and is the
> **Phase 1 R3 entry gate** — citation is NOT counted in Phase 0's "proven"
> subsystem list. Do not claim citation proven until the live run lands rows.

## Pre-flight (BLOCKING)

- [ ] **Perplexity v1 daily quota confirmed.** Decides `--max-pairs` / `--cost-cap`
      and the plist `StartCalendarInterval`. (Origin roadmap Deferred item.) Until
      confirmed, do not schedule `com.dex.bp-citations.plist`.
- [ ] GEO config present: `geo_probe_provider` set (base_url, api_key, model) in
      `~/.config/backlink-publisher/config.toml`.
- [ ] At least one `target_probe_queries` entry for a real target.

## Live run

```bash
# Dry-run first — zero network, prints the plan + cost ceiling:
bp probe-citations --dry-run

# Real probe, bounded:
bp probe-citations --probe --max-pairs 3 --cost-cap 5
```

## Success evidence (what "real output" means)

Query events.db and confirm **non-empty** rows landed, each with floor fields:

```bash
sqlite3 ~/.cache/backlink-publisher/events.db \
  "SELECT count(*) FROM events WHERE kind='citation.observed';"   # >= 1
sqlite3 ~/.cache/backlink-publisher/events.db \
  "SELECT json_extract(payload_json,'$.verdict'),
          json_extract(payload_json,'$.engine'),
          json_extract(payload_json,'$.query')
   FROM events WHERE kind='citation.observed' ORDER BY id DESC LIMIT 5;"
```

- ✅ **Success:** ≥1 `citation.observed` row, `verdict`/`engine`/`query` all populated.
- ❌ **Failure (build-but-silent):** command exits 0 but zero rows, or rows with
  empty floor fields. Do NOT activate scheduling; treat as a live-seam bug.

## After success

- Record the live-run date + row count back in the Phase 0 plan / roadmap.
- citation may then be added to the "proven" list and `com.dex.bp-citations.plist`
  scheduled (Phase 1 R3).
