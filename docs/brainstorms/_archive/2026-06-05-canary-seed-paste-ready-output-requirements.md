---
date: 2026-06-05
topic: canary-seed-paste-ready-output
---

# Canary-Seed Paste-Ready Verdict Output

> **Design pivot (post document-review).** An earlier draft proposed a separate
> `flip-assist` CLI that consumed canary-seed JSONL and emitted a git patch.
> Multi-persona review converged that this was over-engineered for a finite
> ~11-platform, one-time-ish flip: a patch generator against a high-churn source
> file is brittle, a ready-to-apply patch is auto-mutation-minus-one-command (A5
> in letter only), and a raw unified diff is the *least* legible artifact for a
> humanities-background operator. This requirements doc adopts the lighter
> design: **enhance `canary-seed` itself** to print a human-readable verdict
> summary + a paste-ready `register(...)` edit on stderr. One tool, no patch, the
> operator's copy-paste is the genuine human-judgment gate.

## Problem Frame

`canary-seed` (Plan 2026-05-27-001, archived; tool live at `cli/canary_seed.py`)
probes a `dofollow="uncertain"` platform: publishes an OUR-pipeline test post,
inspects the target anchor's `rel`, and emits **one** JSONL verdict
(`dofollow` / `nofollow` / `ambiguous`) on stdout. By design (**A5**) it never
edits source — the operator reads the verdict and **manually** flips the
`dofollow=` flag in `publishing/adapters/__init__.py`.

The friction is the gap between *verdict* and *correct edit*. To act on a
`dofollow` verdict the operator must know that `→True` is not a one-line change:
the registry's validation gate (`registry.py`) requires a ≥80-char rationale
**when `dofollow` is not `True`**, so flipping to `True` means also **removing**
the now-forbidden `rationale=` / `referral_value=` kwargs and the
`_nofollow_rationales` entry — get it wrong and the module fails to import. That
non-obvious multi-edit, computed by hand per platform across the ~11 registered
uncertain platforms (`registry.registered_platforms()` is authoritative; raw
source shows 13 occurrences incl. header-comment examples), is the error-prone
step that leaves verified evidence un-acted-on.

**Fix:** have canary-seed print, alongside its verdict, the exact paste-ready
edit and a plain-language summary — so the operator copies a correct snippet
instead of hand-deriving it, with no new tool and no auto-mutation.

## User Flow

```
$ canary-seed devto          # stdout = JSONL verdict (unchanged contract)
{"platform":"devto","verdict":"dofollow","post_url":"https://…","rel_tokens":[]}

# stderr now also prints a human-readable RECON + paste-ready edit:
  devto → DOFOLLOW ✓   (target anchor rendered dofollow; post: https://…/p/123)
  PASTE into register("devto", …):  dofollow=True
    └ also DELETE:  rationale=_R["devto"],  referral_value="…",  and the
       _nofollow_rationales["devto"] entry   (True forbids them — else import fails)
  ⚠ single canary — a synthetic-post dofollow ≠ guaranteed real-post dofollow;
     re-run to confirm before pasting (a false →True misroutes real dispatch).

$ <operator copies the snippet into __init__.py by hand> && commit
```

## Requirements

**Non-regression (the load-bearing constraint)**
- R1. canary-seed's existing contract is **unchanged**: stdout stays exactly one
  JSONL verdict line per run, exit code stays 0 (advisory). All new output is
  **stderr-only**, so any pipeline/test consuming stdout is unaffected.

**Human-readable summary**
- R2. After the verdict, print to stderr a plain-language one-liner per platform:
  platform, verdict in words (DOFOLLOW / NOFOLLOW / AMBIGUOUS), the canary post
  URL, and the rel evidence. URL is **normalized** (scheme+host+path; query string
  + any userinfo/token-shaped params stripped) so a draft/preview URL can't leak
  credentials into a terminal log the operator may paste elsewhere.

**Paste-ready edit**
- R3. For a `dofollow` or `nofollow` verdict, print the exact edit for that
  platform's `register(...)` block:
  - **`dofollow` → `dofollow=True`:** show the flag change **and** explicitly list
    what must be removed — the `rationale=_R[...]` and `referral_value=...` kwargs
    plus the `_nofollow_rationales[...]` entry (forbidden once `dofollow=True`;
    omitting them breaks import) — and the inline `# … canary pending` comment
    update to a dated canary-confirmed note.
  - **`nofollow` → `dofollow=False`:** show only the flag change; the platform's
    existing `uncertain` rationale **stays valid and is inherited** (no rationale
    work needed — `False` still requires it).
- R4. For an `ambiguous` verdict, print its `reason` (e.g. `anchor_not_found`,
  `publish_failed`, `inspect_failed`, `ssrf_blocked:*`, `no_post_url_returned`)
  and **no edit snippet** — the platform stays `uncertain`. (There are no separate
  "index-failure"/"probe-error" verdicts; they collapse into `ambiguous`+`reason`.)

**Confidence honesty**
- R5. Every verdict is from a **single** synthetic canary post. The summary marks
  this, and a `dofollow` (`→True`) snippet carries an explicit **"re-run to
  confirm before pasting"** caution — because a false `→True` actively misroutes
  real dispatch volume into a stripping platform, whereas a false `→False` only
  conservatively withholds a platform. Asymmetric caution by design.

**Safety**
- R6. **A5 preserved by construction.** The tool emits text the operator copies by
  hand; it produces **no** auto-applicable artifact (no patch, no `--apply`),
  never writes source, and the copy-paste step is the real human-judgment gate.
- R7. Any platform-derived text rendered into the paste-ready snippet (notably the
  post URL and platform name) is **safe for source**: rendered via a literal-safe
  form (so quotes/newlines/backslashes can't break out of the printed Python
  literal a human will paste), and the platform name is validated against the live
  `registered_platforms()` set before a snippet is offered.

## Success Criteria
- Running `canary-seed <p>` for a confident verdict prints a snippet the operator
  can copy into `__init__.py` **verbatim** to make a correct, import-valid edit —
  with **zero hand-computation** of the `→True` removal set.
- canary-seed's stdout JSONL shape and exit-0 contract are byte-for-byte unchanged
  (no consumer/test regression) — verified by the existing canary-seed tests.
- A `→True` snippet from a single canary visibly cautions the operator to re-run
  before pasting.
- No printed URL carries a query string / credential.

## Scope Boundaries
- **No new CLI, no git patch, no `--apply`** — this is purely additional stderr
  output on the existing `canary-seed`.
- **Does not sweep** — canary-seed stays one platform per invocation (the operator
  loops it); batching/`--min-confirmations` is out (YAGNI for a one-time finite set).
- **Does not auto-apply or auto-edit** source (A5).
- **Does not** touch the `dofollow=True` contract-drift path (`canary-targets`) —
  separate demotion/drift cohort.
- **Not** an indexability/SEO oracle — it transcribes the rel verdict only; a
  `dofollow` verdict is a credential-time signal, not a ranking guarantee.

## Key Decisions
- **Enhance canary-seed, not a second tool** (chosen over the `flip-assist` patch
  CLI): one tool, no producer/consumer split, no patch brittleness against a
  swarm-churned file, and the paste step keeps A5 honest. (Document-review
  consensus.)
- **stderr-only, stdout untouched**: protects the existing JSONL contract and its
  tests — the enhancement cannot regress any consumer.
- **`→True` snippet must spell out the removal set**: the registry gate makes
  `→True` a multi-edit (drop rationale + referral_value + `_R` entry) — the whole
  value is encoding that non-obvious step so the operator can't get it wrong.
- **Asymmetric confidence caution** (re-run before `→True`, not before `→False`):
  a false `→True` misroutes real volume; a false `→False` is merely conservative.

## Dependencies / Assumptions
- Value is gated on canary-seed actually being **run** with real bound credentials
  for the uncertain platforms — and per project memory no non-author canary run
  has completed end-to-end, and the owned-account universe is small. The first
  real run may yield only a handful of verdicts; this enhancement makes each of
  those few correctly actionable, but does not create verdicts. (Running it =
  ideation option A, the upstream operational task.)
- Reuses canary-seed's existing publish → `inspect_target_anchor` → verdict path
  and its `_R` / `register(...)` registry shape; the snippet must mirror the exact
  current block format.

## Outstanding Questions

### Deferred to Planning
- [R3][Technical] The exact textual shape of each platform's `register(...)` block
  and `_R[...]` entry the snippet must reproduce (read `__init__.py` +
  `_nofollow_rationales.py`); confirm `→True` removal of `rationale=`/
  `referral_value=`/`_R` has no other consumers (tests, `monolith_budget`,
  `registry.dofollow_rationale`).
- [R2/R7][Technical] URL-normalization + literal-safe rendering helper — reuse an
  existing util if one exists, else a small local one; confirm it strips
  query/userinfo and is repr/JSON-safe.
- [R1][Technical] Where in `canary_seed.py` the stderr RECON is emitted today, so
  the new lines extend the existing RECON block rather than introducing a second
  stderr writer.

## Next Steps
→ `/ce:plan` for structured implementation planning.
