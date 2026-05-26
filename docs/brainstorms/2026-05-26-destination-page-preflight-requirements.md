---
date: 2026-05-26
topic: destination-page-preflight
---

# Destination-Page Preflight

## Problem Frame
The pipeline authors backlink content from `seed_keywords`/`topic` only — it **never reads the
destination page** a backlink points at. A link planted at a `noindex`, soft-404, dead (non-200), or
redirected-away `target_url` is **dead link equity**: budget and a publish slot spent on a target that
passes no SEO value and is a relevance/footprint liability. Today the operator discovers this only after
rankings fail to move. This feature gives the solo operator a way to **read each target page once and
report whether it is reachable and not-obviously-dead** — before content is generated and published.

**Deliberately NOT an indexability oracle.** The checks (reachability/redirect/noindex-tag/soft-404/
title+h1) are *necessary-not-sufficient* signals: a page can pass all of them and still be deindexed via
`rel=canonical` elsewhere, `robots.txt` Disallow (never fetched here), JS-injected `noindex` (the parser
sees static HTML only), crawl-budget, or a manual penalty. The verb reports "not obviously dead," never
"Google will index this." Wording throughout avoids the word *indexable* as a verdict to prevent false
confidence — a green verdict that lies is worse than no check.

Sourced from `docs/ideation/2026-05-26-round9-fresh-pass-ideation.md` (survivor #1; both round-9
critics' top pick). Confidence 80%, complexity **Medium-High** (revised up after review: R4 requires a
new destination-fetch function, not pure reuse — see Key Decisions).

## Requirements

**Invocation & I/O**
- R1. A new standalone CLI verb (working name `preflight-targets`) reads a plan JSONL (the
  `plan-backlinks` output) from stdin or a file argument and processes it on demand. It never runs as
  part of the normal `plan → validate → publish` pipeline.
- R2. It reads each row's `target_url` field, **dedupes** target URLs across the whole plan, and fetches
  each distinct `target_url` **at most once**.
- R3. stdout emits one JSONL receipt object per distinct `target_url`; stderr emits a human-readable
  summary (e.g. "12 targets checked, 3 unhealthy"). The verb **always exits 0** (report-only).
  Honors the project's stdout=data / stderr=diagnostics / exit-0-on-success contract.

**Indexability checks (per target_url)**
- R4. Each receipt records the outcome of these checks against the fetched target page:
  - **Reachability** — HTTP 200 vs non-200 (4xx/5xx) vs unreachable (timeout/DNS/connection error).
  - **Redirect** — whether the request redirected away; record the final URL and whether the final
    host differs from the requested host.
  - **noindex** — `meta robots` `noindex` and/or `X-Robots-Tag: noindex` present.
  - **soft-404** — reuse the existing soft-404 detection (`content/_soft404`).
  - **Structure** — presence of `<title>` and at least one `<h1>`.
- R5. Each receipt carries an overall per-target verdict (e.g. `healthy` / `unhealthy` / `unreachable`)
  plus a list of which specific checks failed, so the operator can see *why* a target is flagged, plus
  the **fetch timestamp** — the verdict is a point-in-time snapshot valid only at fetch time (a plan
  reused over weeks must be re-run; there is no caching/durability claim).
- R6. Fetching reuses the existing content fetch/parse path (`content/fetch.py` + `content/scraper.py`)
  rather than introducing a new HTTP client, and respects the project's existing fetch hygiene
  (timeouts, SSRF/network guards).
- R6a. **[SSRF baseline — non-negotiable]** Because R4 follows redirects and records the final host,
  fetching MUST route through the existing SSRF guard (`_util/net_safety` — `_check_url_for_ssrf` +
  `_SSRFSafeRedirectHandler`) so the initial host AND every redirect hop is re-validated against
  private/loopback/link-local/metadata IP ranges, `https→http` downgrade is refused, and redirects are
  capped. A `target_url` (or any redirect hop) resolving into a blocked range is recorded as
  `ssrf_blocked`, never fetched — and must not cause a non-zero exit (R8 still holds).

**Behavior & reporting**
- R7. The verb is **report-only**: it never blocks, mutates, or rewrites the plan, and never generates
  content. It only reads target pages and reports.
- R8. Exit code is always 0 regardless of how many targets are unhealthy. The operator reads/greps the
  receipt themselves; there is no gate, no `--strict` mode, and no non-zero failure signal in the MVP.

## Success Criteria
- Running the verb on a plan whose `target_url`s include a known-good page, a 404, a `noindex` page, and
  a page that redirects to a different host produces a receipt that correctly distinguishes all four.
- The operator can tell, before generating/publishing content, which target pages will waste link
  equity — and why (which check failed) — without reading any target page manually.
- A normal `validate-backlinks` run is unaffected (no new network fetch, no slowdown) because the check
  lives in a separate on-demand verb.

## Scope Boundaries
- **Anchor↔destination match is OUT of scope for MVP** (anchor language/topic vs destination
  title/h1/locale). Deferred to a follow-up; the verb checks indexability/health only.
- **Only `target_url` is checked.** `main_domain` (money-site root) and other link-kind targets are not
  fetched in the MVP.
- **No noindex opt-out / allowlist in the MVP.** Nothing gates, so an intentionally-`noindex` tier-2
  target simply reports a `noindex` finding the operator can ignore. (See deferred question.)
- No gating, no `--strict`/non-zero exit, no plan mutation, no content generation, no caching layer.
- No runtime LLM (hard project rule) — checks are HTTP/DOM/string only.

## Key Decisions
- **Indexability-only MVP**: table-stakes dead-equity detection first; defer the riskier locale/topic
  heuristics. Lowest risk, clearest value.
- **`target_url` only**: the specific target page is the one most likely to be noindex/404/redirected;
  fewest fetches, sharpest signal.
- **Standalone verb, not a validate flag**: network fetches stay off the main pipeline so normal
  validates remain fast and offline; the verb dedupes target_urls campaign-wide.
- **Always exit 0, report-only**: purest "never gates" reading; preserves the exit-0-on-success contract
  and keeps the operator in control of interpretation.
- **Reuse existing fetch/scraper/soft-404 path**: all primitives are verified present
  (`scraper.fetch_work_metadata`, `_soft404.is_soft_404_title`, title/h1 extractors); the gap is purely
  that they are never aimed at the target URL.

## Dependencies / Assumptions
- Assumes plan rows reliably carry a `target_url` (confirmed in `schema.py`). Rows missing `target_url`
  should be skipped with a stderr note, not error out.
- Tests that exercise real fetching must use the `real_content_fetch` marker, since autouse conftest
  fixtures block content fetches by default.

## Outstanding Questions

### Deferred to Planning
- [Affects R4][Technical] Exact mechanism for `noindex` (meta robots vs `X-Robots-Tag` header) and
  redirect-final-URL extraction within the existing fetch path — confirm what `content/fetch.py`
  already exposes vs what must be added.
- [Affects R6][Technical] How the existing SSRF/network guards apply to operator-supplied `target_url`s
  (the targets are operator's own money pages, but the guard path should be confirmed).
- [Affects R2][Technical] Receipt object field shape/keys and how the verb is wired into the registry /
  console-scripts / `python -m` entry conventions.
- [Affects scope][Product, deferred] If `noindex` findings prove noisy for operators with intentional
  tier-2 noindex targets, revisit a per-row `expect_noindex` hint or a config allowlist.

## Next Steps
→ `/ce:plan` for structured implementation planning
