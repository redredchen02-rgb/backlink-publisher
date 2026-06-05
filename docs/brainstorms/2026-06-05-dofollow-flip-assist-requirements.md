---
date: 2026-06-05
topic: dofollow-flip-assist
---

# Dofollow Flip-Assist (canary verdict → reviewable registry patch)

> ⛔ **SUPERSEDED (2026-06-05)** by
> `2026-06-05-canary-seed-paste-ready-output-requirements.md`. Document-review
> found the separate patch-generating CLI over-engineered for a finite ~11-platform
> one-time flip (brittle patch vs high-churn source, A5-in-letter-only, raw diff
> poorly suited to the operator). The chosen design enhances `canary-seed` to print
> a paste-ready `register(...)` edit on stderr instead. Kept for provenance only —
> do not plan from this file.

## Problem Frame

`canary-seed` (Plan 2026-05-27-001, now in `docs/_archive/plans/`; tool live at
`cli/canary_seed.py`) probes a `dofollow="uncertain"` platform: it publishes an
OUR-pipeline test post, inspects the target anchor's `rel`, and emits **one**
JSONL verdict (`dofollow` / `nofollow` / `ambiguous`). It takes a **single
platform** per invocation — there is no built-in 13→1 sweep loop; the operator
runs it once per platform (`for p in …; do canary-seed "$p"; done`). By design
(**A5**) it never edits source — the operator must then **manually** open
`publishing/adapters/__init__.py` and change the `dofollow=` flag for each of the
**~11 registered** uncertain platforms (`registry.registered_platforms()` is
authoritative; raw source shows 13 `dofollow="uncertain"` occurrences incl.
header-comment examples — planning confirms the live count).

That manual verdict→flip step is the friction: tedious across 13 platforms,
error-prone (wrong line, malformed rationale that fails the ≥80-char gate), and
it leaves verified evidence un-acted-on. **Flip-assist closes that loop** by
turning canary-seed's JSONL verdicts into a single **reviewable git patch** the
operator inspects and applies — removing the hand-editing without ever silently
mutating source (A5 preserved: the operator still consciously applies + commits).

This is the *only* net-new slice of ideation idea #1 — the canary sweep itself
is already shipped (`cli/canary_seed.py`). See
`docs/ideation/2026-06-05-dofollow-throughput-ideation.md`.

## User Flow

```
# canary-seed is per-platform; sweep is a shell loop (each run = a real
# publish + settle window + a manual canary-post delete per its delete_hint)
$ for p in <uncertain platforms>; do canary-seed "$p"; done >> verdicts.jsonl
$ flip-assist < verdicts.jsonl > flips.patch
  # reads verdicts, drafts a unified diff for the confident flips,
  # skips ambiguous/errored, annotates low-confidence (single-run) flips
$ git apply --check flips.patch          # fails loud if base drifted
$ git apply flips.patch && git diff      # operator reviews
$ <edit rationale wording if desired> && git commit
```

## Requirements

**Patch generation**
- R1. Read canary-seed JSONL verdicts (stdin or file args) and emit a single
  **unified diff** (stdout, or `-o <file>`) that, when applied via `git apply`,
  flips the registry `dofollow=` flag: `dofollow` verdict → `dofollow=True`;
  `nofollow` verdict → `dofollow=False`. The diff may span **two files**
  (`adapters/__init__.py` and `_nofollow_rationales.py`) — see R2. The tool
  itself **never writes source directly** (A5); it only produces a patch the
  operator reviews and applies.
- R2. The patch must keep the registry **valid after apply**. The validation gate
  (`registry.py`) requires a ≥80-char rationale **when `dofollow` is not `True`**
  — so the asymmetry is the reverse of the naive reading:
  - **`→False` (nofollow):** the platform's existing `uncertain` rationale stays
    valid and is **inherited as-is** — no rationale add is required (optional
    re-wording only). Only the `dofollow=` line flips.
  - **`→True` (dofollow):** rationale becomes forbidden/dead. The patch **must
    coherently remove** the platform's now-orphaned `_nofollow_rationales` entry
    **and** its `rationale=_R[...]` + `referral_value=...` kwargs in
    `__init__.py`, and update the inline `# … canary pending` comment to a dated
    canary-confirmed note. A `→True` flip that leaves these behind breaks the
    registry — so this is a hard requirement, not deferred. (This load-bearing
    multi-edit case is the real complexity, not the `→False` case.)
- R3. Each proposed flip is annotated in the patch (comment/hunk context) with
  its **evidence**: verdict, post URL, and how many confirming observations it
  is based on. A flip backed by a **single** observation is marked
  **low-confidence — consider re-running** (the synthetic-post-may-differ-from-
  real-post risk from the contract-canary brainstorm).

**Verdict handling**
- R4. canary-seed's `verdict` field is exactly one of `dofollow` | `nofollow` |
  `ambiguous`. Only `dofollow` and `nofollow` produce flips. All `ambiguous`
  rows — which carry a free-form `reason` (e.g. `anchor_not_found`,
  `publish_failed`, `inspect_failed`, `ssrf_blocked:*`, `no_post_url_returned`) —
  produce **no flip**; they are echoed to stderr RECON **with their reason** and
  the platform stays `uncertain`. (There are no separate "index-failure" /
  "probe-error" verdict values — those collapse into `ambiguous`+`reason`.)
- R5. A verdict whose platform is **no longer `uncertain`** in the current
  registry (already flipped, drifted, or retired) is **skipped with a warning**,
  never patched (guards against stale/out-of-date verdict files).

**Confidence gate**
- R6. Default behavior: draft a patch from a **single** (n=1) verdict, flagged
  low-confidence per R3 (the operator-reviewed patch is the final gate).
- R7. `--min-confirmations N` filters to flips with ≥N agreeing observations for
  the same platform across the supplied verdicts; conflicting verdicts for one
  platform (some dofollow, some nofollow) are **never** auto-drafted — reported
  as conflict, left `uncertain`.

**Contract**
- R8. Advisory diagnostic: **exit 0** even when no flips are produced; mirrors
  the canary-seed stdout=data / stderr=recon / exit-0 contract. Empty input or
  zero confident flips → empty patch + recon note, exit 0.

**Trust boundary & sanitization (platform-derived input → source code)**
- R9. **Verdict fields are untrusted.** `post_url`, `rel` tokens, and the
  platform name in the JSONL originate from a third-party platform's rendered
  page (canary-seed emits `post_url = result.published_url or draft_url`). They
  flow into a Python string literal (rationale) and patch context, i.e. into
  source that gets committed. flip-assist **must**: (a) validate each row's
  platform against the live `registered_platforms()` set and reject unknown ones
  (guards a forged/hostile `verdicts.jsonl`); (b) render any platform-derived
  text into source via a literal-safe encoder (`repr()` / JSON string), never raw
  f-string concatenation, so quotes/newlines/backslashes/comment bytes cannot
  break out of the literal or spoof patch context; (c) normalize `post_url` to
  `scheme+host+path` — **strip query string + any userinfo/token-shaped params**
  before it enters a rationale or annotation, so draft/preview URLs don't leak
  credentials into committed source. (Specific encoder choice → planning.)

## Success Criteria
- A full canary-seed → flip-assist → `git apply` → commit loop flips all
  confidently-resolved uncertain platforms with **zero hand-editing of
  `__init__.py` / `_nofollow_rationales`**, and the applied result passes the
  registry's existing validation (flag values + ≥80-char rationale gate).
- The tool never modifies source on its own (A5 holds): with no `git apply`,
  the working tree is unchanged.
- A stale verdict (platform already flipped) cannot corrupt the registry — it is
  skipped with a warning, not patched.
- Single-observation flips are visibly marked low-confidence so the operator
  isn't lulled into trusting a possible fluke.

## Scope Boundaries
- **Does not** publish, recheck, or re-run canaries — it only consumes
  canary-seed's existing JSONL output (clean producer/consumer split).
- **Does not** auto-apply or auto-commit — output is a patch; the operator is
  the apply/commit gate (A5).
- **Does not** touch the dofollow=True contract-drift monitoring path
  (`canary-targets`) — that is the *demotion/drift* cohort, a separate concern.
- **Not** an indexability or SEO-inclusion oracle — it only transcribes
  canary-seed's rel verdict into a registry edit.

## Key Decisions
- **Output = reviewable git patch** (not in-place `--apply`, not paste-the-line):
  best fits the existing JSONL→stdout pipeline style and most strongly preserves
  A5 — the source is untouched until the operator runs `git apply`.
- **n=1 drafts, low-confidence-marked** (not ≥2-required): the operator-reviewed
  patch is already a confidence gate; requiring multi-run accumulation adds state
  + cross-day friction. `--min-confirmations` is the opt-in for the cautious.
- **Producer/consumer split from canary-seed**: flip-assist reads verdicts, does
  not re-run them — keeps each tool single-purpose and testable on fixture JSONL.
- **Patch must keep the registry valid** (R2): a `→False` flip without a
  conformant rationale would break the ≥80-char gate, so rationale drafting is in
  scope, not deferred.

## Dependencies / Assumptions
- Assumes canary-seed's JSONL verdict schema is stable enough to consume; the
  exact field names are a planning-time read of `cli/canary_seed.py`.
- Assumes the registry `dofollow=` lines and `_nofollow_rationales` entries are
  textually locatable per platform for patch generation (planning verifies the
  precise edit anchors).
- Value depends on canary-seed actually being **run** with real bound
  credentials for the uncertain platforms — flip-assist has nothing to act on
  until verdicts exist. (Running it is the separate operational task, ideation
  option A.)

## Outstanding Questions

### Deferred to Planning
- [R1/R2][Technical] Exact canary-seed JSONL field names (read `cli/canary_seed.py`:
  `platform`, `verdict`, `post_url`, `rel_tokens`, `reason?`, `delete_hint`, …) —
  the schema has no version field, so flip-assist's parser must fail loud on
  unexpected shape.
- [R1/R2/R5][Technical] **Patch anchoring strategy against a high-churn file.**
  `__init__.py` is one of the most actively swarm-rewritten files (4 of its last
  8 commits touched it); a line-context unified diff will reject on drift. Decide:
  anchor each edit on the unique `register("<slug>", …)` block (AST/block-scan
  keyed on the platform positional), regenerate-on-reject, and verify the live
  `dofollow_status(platform)` programmatically for R5's stale-guard rather than
  parsing the flag from text. Confirm `→True` removal of `rationale=`/
  `referral_value=` + the `_R[...]` entry has no other consumers (tests,
  monolith_budget, `registry.dofollow_rationale`).
- [R7][Technical] How "agreeing observations" are grouped across concatenated
  JSONL runs (by platform + verdict; within-run exact duplicates deduped;
  conflict = mixed verdicts → no draft).

## Next Steps
→ `/ce:plan` for structured implementation planning.
