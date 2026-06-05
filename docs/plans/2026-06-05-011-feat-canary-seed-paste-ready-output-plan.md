---
title: "feat: canary-seed paste-ready verdict output"
type: feat
status: completed
date: 2026-06-05
origin: docs/brainstorms/2026-06-05-canary-seed-paste-ready-output-requirements.md
---

# feat: canary-seed paste-ready verdict output

## Overview

Enhance the existing `canary-seed` CLI so that, alongside its machine verdict, it
prints to **stderr** (a) a plain-language verdict summary and (b) a **guided edit
checklist** for that platform's `register(...)` block: the exact new `dofollow=`
value plus the precise set of changes the operator must make. The operator follows
the checklist to edit `publishing/adapters/__init__.py` instead of hand-deriving the
4-edit `→True` procedure — closing most of the verdict→flip friction without a new
tool, without a git patch, and without auto-mutating source (A5 preserved: the
operator's manual edit is the human-judgment gate). `canary-seed`'s stdout JSONL +
exit-0 contract is unchanged.

> **Honesty note (post-review):** the checklist is **not** a literally paste-ready
> full `register(...)` line. The formatter sees only the verdict receipt fields
> (`platform, verdict, post_url, rel_tokens`); it cannot reconstruct the block's
> adapter class, `**<PLATFORM>_MANIFEST` splat, or per-platform extras like
> `visibility="retired"`. So it emits the `dofollow=` value to set + a checklist of
> what to change/remove for that platform (an annotated template), not a wholesale
> copy-paste of the line. This still removes the load-bearing friction (knowing the
> exact 4-edit `→True` set) while staying honest about what is mechanically possible.

## Problem Frame

`canary-seed` (`cli/canary_seed.py`) already probes a `dofollow="uncertain"`
platform, publishes an OUR-pipeline test post, inspects the target anchor's `rel`,
and emits one JSONL verdict on stdout (`dofollow` / `nofollow` / `ambiguous`). By
design (**A5**) it never edits source — the operator manually flips the flag. The
friction is the gap between *verdict* and *correct edit*: a `→True` flip is **not**
one line — the registry validation gate (`registry.py`) requires a ≥80-char
rationale **when `dofollow` is not `True`**, so flipping to `True` also means
removing the now-forbidden `rationale=` / `referral_value=` kwargs and the
`_nofollow_rationales` (`_R`) entry, or the module fails to import. Hand-computing
that per platform is the error-prone step the verdict leaves un-actioned (see
origin: `docs/brainstorms/2026-06-05-canary-seed-paste-ready-output-requirements.md`).

## Requirements Trace

- R1. New output is **stderr-only**; stdout JSONL shape + exit-0 contract unchanged
  (no consumer/test regression).
- R2. Print a plain-language per-platform summary: platform, verdict in words, the
  **normalized** canary post URL (query/fragment + userinfo stripped), rel evidence.
- R3. For `dofollow`/`nofollow`, print the guided edit checklist (an annotated
  template keyed by platform — **not** a literal full-line paste; see the Overview
  honesty note):
  - `→True`: set `dofollow=True` **and** the full removal set (delete the
    `rationale=_R[...]` kwarg, the `referral_value=...` kwarg, and the `_R["x"]`
    entry in `_nofollow_rationales.py`) + update the inline `# … canary pending`
    comment to a dated canary-confirmed note + a reminder to add a
    `dofollow_status(...) is True` regression test. Preserve all other existing
    kwargs (adapter class, `**<PLATFORM>_MANIFEST`, `visibility=`, …) — the
    checklist names them as "leave unchanged".
  - `→False`: set `dofollow=False` only; existing rationale + `referral_value`
    inherited (no change — both still required while `dofollow` is not `True`).
- R4. `ambiguous` → print its `reason`, **no edit checklist**, platform stays uncertain.
- R5. Single-observation honesty: every verdict is one synthetic canary; a `→True`
  checklist carries an explicit **"re-run to confirm before editing"** caution
  (asymmetric — false `→True` misroutes real dispatch; false `→False` is conservative).
- R6. A5 preserved: no auto-applicable artifact, never writes source.
- R7. **All platform-derived text written to stderr is safe** (not just the
  checklist): `post_url` (and `delete_hint`, which embeds it) normalized — strip
  query + fragment + `params` segment + userinfo in a single `urlparse`/`urlunparse`
  pass; `rel_tokens`, `reason`, and any value placed in the checklist rendered
  literal-safe (`json.dumps`/`repr`) **and** stripped of control/ANSI characters
  (prevents terminal spoofing of the human-read stderr the operator copies from);
  platform validated against `registered_platforms()` before a checklist is offered.

## Scope Boundaries

- No new CLI, no git patch, no `--apply` — additive stderr on existing `canary-seed`.
- Does not change stdout JSONL, the verdict vocabulary, or exit code.
- Does not sweep (still one platform per invocation); no `--min-confirmations`.
- Does not auto-edit source (A5); does not touch the `dofollow=True` contract-drift
  path (`canary-targets`).
- Not an indexability/SEO oracle — transcribes the rel verdict only.

## Context & Research

### Relevant Code and Patterns

- `src/backlink_publisher/cli/canary_seed.py` — `main()`: stdout JSONL at **:245**
  (`print(json.dumps(receipt))`); receipt fields built **:228-243**
  (`platform, post_url, target_url, verdict, rel_tokens, needs_browser_check,
  delete_hint, fetched_at, duration_s`, optional `reason`). Existing stderr writer
  is `canary_logger.recon(...)` at **:248-261** — but `recon()` emits **machine JSON**
  to stderr (`logger.py:160`), so the human summary is a **new plain
  `print(..., file=sys.stderr)`** added in the same `:247-261` block. `_map_verdict()`
  **:91-102** → `dofollow|nofollow|ambiguous`. Registry already imported **:39**
  (`dofollow_status, registered_platforms`); membership validated **:156-163**.
- `src/backlink_publisher/publishing/adapters/__init__.py` — register block shape
  (e.g. hashnode): `register("hashnode", HashnodeGraphQLAdapter, dofollow="uncertain",
  rationale=_R["hashnode"], referral_value="high", **HASHNODE_MANIFEST)`; `_R` import
  at **:68** from `._nofollow_rationales`.
- `src/backlink_publisher/publishing/adapters/_nofollow_rationales.py` — `NOFOLLOW_RATIONALES`
  (`_R`) dict, ≥80-char string entries.
- `src/backlink_publisher/publishing/registry.py` **:355-373** — gate: `dofollow in
  (False, "uncertain")` requires rationale ≥80 chars **and** `referral_value`;
  `dofollow=True` skips the gate (→ those kwargs become dead, `_R` entry orphaned).
  `dofollow_rationale` accessor at **:497**.
- Leaf-module extraction precedent: `_nofollow_rationales.py`, `cli/.../_candidates.py`,
  `_engine.py` — same pattern this plan mirrors for the formatter.
- `src/backlink_publisher/_util/url.py:154` `strip_fragment_query(url)` (strips
  query+fragment, preserves path) — reuse for R2/R7. **Userinfo-strip ABSENT** →
  manual `netloc.split("@")[-1]`. **No literal-safe helper** → use stdlib
  `json.dumps`/`repr`.

### Institutional Learnings

- A5 is already decided in-code (`canary_seed.py:10-14`) — this feature is the
  paste-ready helper for that exact manual edit; stays A5-compliant.
- The complete `→True` flip procedure (4 edits + regression test) is documented:
  `docs/runbooks/2026-05-25-dofollow-canary-closeout.md:43-48`. **Snippet completeness
  is a correctness requirement** — omitting the `_R` deletion makes the operator's
  paste `KeyError` on import; omitting the regression-test reminder silently regresses.
- stdout-contract discipline: the canary verdict was once silently dropped at a
  serialization seam (`docs/solutions/integration-issues/dofollow-canary-verdict-dropped-at-publish-output-seam-2026-05-25.md`)
  → assert stdout JSONL is byte-unchanged.
- Report the **target backlink's** rel, not the page-wide `nofollow_detected` flag
  (`grep-dofollow-map-before-shipping-adapter`, same integration-issues doc §4).
- **SLOC budget is the live risk:** `monolith_budget.toml:78` — `canary_seed.py`
  ceiling **230**, current **196** (~34 headroom). Extract the formatter into a leaf
  module so wiring adds only a call + a few print lines. No `complexity_budget` entry
  for `main()`, but the global CC-30 backstop applies → keep logic in small helpers.
- Roster/shortlist consistency: `docs/discovery/canary-pending.md` +
  `tests/test_canary_pending_deadline.py`, `dofollow-platform-shortlist.md:42-43` —
  do not contradict if output references the roster (this plan does not edit them).

### External References

- None — internal CLI with strong local patterns; no external research warranted.

## Key Technical Decisions

- **Extract a leaf formatter module, not inline in `main()`**: SLOC headroom is ~34
  and a multi-line snippet builder would risk the 230 ceiling + CC-30 backstop. A
  pure-function module is also unit-testable in isolation (snippet completeness =
  correctness). Mirrors the `_nofollow_rationales.py` leaf pattern.
- **stderr-only, stdout untouched**: protects the firmly-locked JSONL/exit-0 contract
  and its tests; the human summary is a new `print(file=sys.stderr)` beside the
  existing `recon()` machine-JSON call (do not route human text through `recon()`).
- **Guided checklist, not a literal full-line paste** (post-review correction): the
  formatter only sees `platform, verdict, post_url, rel_tokens`, so it cannot
  reconstruct the real register block (adapter class, `**<PLATFORM>_MANIFEST`,
  `visibility=`, …). It emits the `dofollow=` value + a per-platform checklist of
  changes/removals (the 4-edit `→True` set + regression-test reminder), naming other
  kwargs as "leave unchanged". Encoding that non-obvious 4-edit set is the feature's
  whole value; over-claiming "paste-ready" would be dishonest and reintroduce the
  hand-reconcile friction it claims to remove.
- **Source-safety via stdlib + existing url helper, applied to ALL stderr text**:
  one `urlparse`/`urlunparse` normalize that drops query+fragment+params+userinfo
  (reuse `strip_fragment_query` semantics but extend, since it preserves netloc/params);
  `json.dumps`/`repr` + control/ANSI strip for `rel_tokens`/`reason`/checklist values;
  `registered_platforms()` membership check before offering a checklist. (Scope is the
  whole summary, not just the checklist — the operator copies from this stderr stream.)
- **Asymmetric confidence caution**: re-run warning on `→True` only.

## Open Questions

### Resolved During Planning

- Where to emit human text: new `print(file=sys.stderr)` in the `:247-261` block, not
  via `recon()` (which is machine-JSON).
- Whether stdout changes: no — stderr-only (R1).
- `→True` edit set: flip flag + drop `rationale=`/`referral_value=` + delete `_R` entry
  + add `dofollow_status(...) is True` regression test (per runbook).
- URL/literal safety: `strip_fragment_query` + manual userinfo strip + `json.dumps`.

### Deferred to Implementation

- Exact human-readable wording/layout of the summary + snippet (cosmetic; converge
  during implementation against the test's substring assertions).
- Whether the formatter lives in `cli/_canary_flip_hint.py` vs another leaf path —
  pick the name that matches sibling `cli/` leaf modules at implementation time.

## Implementation Units

- [ ] **Unit 1: verdict→summary/snippet formatter (leaf module)**

**Goal:** A pure-function module that turns a verdict receipt into (a) a
plain-language summary string and (b) the paste-ready `register(...)` edit text,
with all source-safety handling — the testable core of the feature.

**Requirements:** R2, R3, R4, R5, R7

**Dependencies:** None

**Files:**
- Create: `src/backlink_publisher/cli/_canary_flip_hint.py`
- Test: `tests/test_canary_flip_hint.py`

**Approach:**
- Pure functions taking the receipt fields already available in `main()`
  (`platform`, `verdict`, `post_url`, `rel_tokens`) → return formatted stderr text
  (no I/O inside the module; `main()` does the printing in Unit 2).
- Verdict branches: `dofollow` → summary + guided checklist with `dofollow=True`
  **and** the removal set (delete `rationale=_R[...]`, `referral_value=...`, the
  `_R["<platform>"]` entry) + dated comment update + regression-test reminder + the
  R5 re-run caution, naming other kwargs "leave unchanged" (the formatter cannot
  reconstruct the full register line — see Key Decisions). `nofollow` → summary +
  `dofollow=False` change only (rationale inherited). `ambiguous` → summary with
  `reason`, no checklist.
- Source-safety (applies to the whole returned stderr text, summary included):
  one normalize pass on `post_url` that strips query+fragment+params+userinfo (extend
  `_util/url.strip_fragment_query`, which preserves netloc+params, with a `urlparse`
  rebuild dropping `params` and `netloc.split("@")[-1]`); render `rel_tokens`,
  `reason`, and any checklist value via `json.dumps`/`repr` **and** strip control/ANSI
  chars; validate `platform in registered_platforms()` before producing a checklist
  (unknown platform → summary-only + warning, no checklist).

**Execution note:** Test-first — snippet completeness is a correctness requirement
(a missing `_R`-deletion instruction breaks the operator's paste at import).

**Patterns to follow:** leaf-module shape of `_nofollow_rationales.py`; verdict vocab
from `_map_verdict` (`canary_seed.py:91-102`); `strip_fragment_query` (`_util/url.py:154`).

**Test scenarios:**
- Happy path (`dofollow`): output contains `dofollow=True`, an instruction to remove
  `rationale=`, `referral_value=`, and the `_R["<platform>"]` entry, a "leave other
  kwargs unchanged" note, the regression-test reminder, and the R5 re-run caution.
  (R3, R5)
- Happy path (`nofollow`): output contains `dofollow=False` and does **not** instruct
  removing the rationale (inherited). (R3)
- Edge (`ambiguous` with `reason="anchor_not_found"`): summary includes the reason and
  **no** checklist (`register(` snippet absent). (R4)
- Source-safety URL: a `post_url` with a query string, a `;jsessionid=…` params
  segment, **and** `user:pass@` userinfo is emitted with all four (query, fragment,
  params, userinfo) stripped. (R7)
- Source-safety injection: a `post_url`/`rel_token`/`reason` containing a `"`,
  a newline, a backslash, or an ANSI/control sequence is neutralized in **both** the
  checklist (literal-safe via `json.dumps`/`repr`) and the plain-language summary
  (control/ANSI stripped) — assert a crafted `rel_token` resembling `register(` text
  cannot appear as an executable-looking line. (R7)
- Defensive (not reached at runtime — `main()` pre-validates at canary_seed.py:156-163):
  platform not in `registered_platforms()` → summary-only, warning, no checklist. (R7)
- Edge: `rel_tokens` empty vs `["nofollow"]` reflected correctly in the summary. (R2)

**Verification:** `tests/test_canary_flip_hint.py` green; the module performs no I/O
and contains no `dofollow`-status mutation. Add a `[files."src/backlink_publisher/cli/_canary_flip_hint.py"]`
entry to `monolith_budget.toml` (with an ≥80-char rationale) so
`tests/test_no_monolith_regrowth.py` does not fail on the new tracked file; if any
new helper trips the global CC-30 backstop, keep branches in small functions.

- [ ] **Unit 2: wire the formatter into canary-seed stderr (non-regression)**

**Goal:** Call the Unit 1 formatter in `main()` and print its output to stderr
alongside the existing `recon()`, without touching stdout, the receipt, or the exit code.

**Requirements:** R1, R6

**Dependencies:** Unit 1

**Files:**
- Modify: `src/backlink_publisher/cli/canary_seed.py` (the `:247-261` emit block)
- Test: `tests/test_cli_canary_seed.py` (extend)

**Approach:**
- After the stdout `print(json.dumps(receipt))` (:245) and beside the existing
  `recon()` call, add `print(format_hint(...), file=sys.stderr)` using Unit 1. Keep
  additions minimal to preserve the SLOC ceiling (logic lives in Unit 1).
- Change nothing about the receipt dict, stdout, or `return 0`.

**Execution note:** Test-first on the non-regression assertion. Do **not** assert
byte-identical stdout — the receipt embeds `fetched_at` (`datetime.now`) and
`duration_s` (`time.monotonic`), which vary per run. Assert the stdout JSONL has the
identical **key set**, the same `verdict`, and unchanged **non-timestamp** field
values, plus exit 0 (mirrors the existing `:134-187` schema asserts). Freeze time
only if a stricter comparison is wanted.

**Patterns to follow:** existing `_run()` / `_parse_jsonl()` harness in
`tests/test_cli_canary_seed.py` (:104-120); existing stderr-RECON call site.

**Test scenarios:**
- Non-regression (R1): for each verdict type, stdout is still exactly one JSONL line
  with the unchanged field set and `verdict`; exit code 0. (Compare against the
  current `:134-187` contract asserts.)
- Integration (`dofollow` run, monkeypatched verify): stderr now contains the summary
  + the guided edit checklist (`dofollow=True` + removal set) for that platform. (R2, R3)
- Integration (`ambiguous` run): stderr contains the summary + reason, no checklist. (R4)
- A5 (R6): the run writes no changes to `adapters/__init__.py` / `_nofollow_rationales.py`
  (tool emits text only).

**Verification:** `tests/test_cli_canary_seed.py` green including the new stdout
non-regression assertion (key set + verdict + non-timestamp values + exit 0, not
byte-identical); `radon raw -s cli/canary_seed.py` stays ≤230 SLOC
(`monolith_budget.toml`) **after** wiring + imports (re-check post-Unit 2, not just
post-Unit 1); full canary-seed suite passes.

## System-Wide Impact

- **Interaction graph:** only `canary-seed`'s stderr path; the formatter is a new leaf
  with no other importers. No change to publish/recheck/dispatch.
- **Error propagation:** formatter is pure + total (handles all three verdicts +
  unknown platform); a formatting failure must not break the verdict emission — keep
  the stderr print after the stdout print so a hint error can never suppress the JSONL.
- **State lifecycle risks:** none — no persistence, no source mutation (A5).
- **API surface parity:** `canary-targets` (the drift cohort) is intentionally
  untouched; only the uncertain-promotion tool gains output.
- **Unchanged invariants:** `canary-seed` stdout JSONL schema, verdict vocabulary,
  exit-0 contract; the registry value-validation gate; all adapter registrations.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| SLOC ceiling (196/230) bumped by inline formatting | Logic in the Unit 1 leaf module; Unit 2 adds only a call + print. Verify radon ≤230. |
| Snippet omits an edit → operator paste breaks import | Snippet completeness is a tested correctness requirement (Unit 1 happy-path asserts all 4 `→True` edits + regression-test reminder). |
| Platform-derived text injects/spoofs in stderr (URL, rel_tokens, reason — summary *and* checklist) | R7: normalize URL (strip query+fragment+params+userinfo) + render all platform values literal-safe (`json.dumps`/`repr`) + strip control/ANSI; validate platform ∈ `registered_platforms()`. Tested in Unit 1 injection scenario. |
| stdout contract regressed | Unit 2 asserts stdout key set + verdict + non-timestamp values + exit 0 (not byte-identical — `fetched_at`/`duration_s` vary per run). |
| Over-claiming "paste-ready" reintroduces hand-reconcile friction | Reframed to a guided checklist (annotated template) — the formatter can't see the adapter class / manifest splat, so it emits the `dofollow=` value + named edit set, honest about what's mechanical. |
| Value gated upstream (canary-seed needs real creds; non-author run never completed) | Accepted — but verdicts are not purely hypothetical: per memory ~73 confirmed live-dofollow links exist on the author path, and confirming any uncertain platform widens the routable pool. This makes each *existing/future* verdict correctly actionable; producing verdicts is the separate operational task (ideation option A). |

## Documentation / Operational Notes

- No new env vars, flags, or rollout. If the printed snippet ever references the
  canary-pending roster, keep consistent with `docs/discovery/canary-pending.md`
  (this plan does not edit it).

## Sources & References

- **Origin document:** docs/brainstorms/2026-06-05-canary-seed-paste-ready-output-requirements.md
- Related code: `cli/canary_seed.py:91-102,228-261`, `publishing/registry.py:355-373`,
  `publishing/adapters/__init__.py:68`, `_util/url.py:154`
- Runbook: `docs/runbooks/2026-05-25-dofollow-canary-closeout.md:43-48`
- Budget: `monolith_budget.toml:78`
