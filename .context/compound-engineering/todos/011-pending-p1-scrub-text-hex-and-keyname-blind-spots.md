---
status: pending
priority: p1
issue_id: "011"
tags: [security, redaction, hardening-sweep]
dependencies: []
---

# scrub_text() has structural blind spots for hex-encoded and unrecognized-key credentials

The D3 unit of `docs/plans/2026-07-06-002-opt-hidden-debt-hardening-sweep-plan.md` newly wires `events/scrubber.py::scrub_text()` into three `cli/_bind/` call sites specifically to prevent credential-adjacent exception text from leaking to operators. The adversarial code-review pass (run `20260706-140906-a92c9d99`) found that `scrub_text()` itself — pre-existing, unchanged by this diff — has two coverage gaps that undermine that guarantee for a subset of realistic secret shapes.

## Problem Statement

`scrub_text()` (`src/backlink_publisher/events/scrubber.py`) is the sole redaction mechanism the D3 fixes (chrome_backend.py, bind_channel.py, _driver_impl.py) rely on to keep credential-adjacent exception text out of operator-visible output. Two gaps mean certain secret shapes pass through unredacted:

1. **Hex-encoded secrets of length != 64 evade both the dedicated regex and the entropy fallback.** The `sha256_hex_token` pattern only matches exactly 64 hex chars. The high-entropy fallback (`_HIGH_ENTROPY_THRESHOLD = 4.5`) can never catch ANY hex string regardless of length, because hex's 16-symbol alphabet caps Shannon entropy at `log2(16) = 4.0` — mathematically below the 4.5 threshold. A 32/40/48-char hex-encoded session key or API token (a common shape — e.g. legacy GitHub PATs were 40-char hex) sails through unredacted if it doesn't match one of the other named patterns.
2. **The `session_token` key-name pattern only fires for a fixed prefix allowlist** (`refresh|access|session|csrf|xsrf|auth` + `[-_]?token`, or bare `sessionid|session|sid|csrf|xsrf`). A bare `token=`, `api_key=`, `secret=`, or `password=` key with a value under 32 chars (below the entropy fallback's minimum length) evades every pattern.

## Findings

- `src/backlink_publisher/events/scrubber.py:96-99` (`_HIGH_ENTROPY_THRESHOLD = 4.5`, `_HIGH_ENTROPY_MIN_LEN = 32`) — verified independently: max possible Shannon entropy for a hex alphabet (16 symbols) is exactly `log2(16) = 4.0`, which can never reach 4.5. This is not a tuning issue; no threshold >= 4.0 will ever catch hex via the entropy path.
- `src/backlink_publisher/events/scrubber.py:77-89` (`session_token` pattern) — confirmed via direct regex reading: the alternation requires one of a fixed list of prefixes; bare `token`, `api_key`, `secret`, `password` are not in that list.
- The module's own docstring already flags the entropy threshold as "deferred to implementation... target false-positive rate <= 5%" (i.e., acknowledged as provisional) — but the *structural* hex-impossibility at 4.5 is a sharper, previously-unstated fact.
- This function is shared, general-purpose security infrastructure (also used by `events/_project_reducers.py`), so a fix here benefits every caller, not just D3's three new sites.

## Proposed Solutions

### Option 1: Add a dedicated hex-token pattern for common lengths (32/40/48 chars), mirroring the existing 64-char `sha256_hex_token` pattern

**Approach:** Add regex patterns for `\b[0-9a-f]{32}\b`, `\b[0-9a-f]{40}\b`, `\b[0-9a-f]{48}\b` (case-insensitive), following the existing `sha256_hex_token` precedent.

**Pros:** Mechanical, low-risk, follows an established pattern in the same file.
**Cons:** Still misses arbitrary-length hex; a moving target if new hex-shaped credential formats emerge.
**Effort:** 1-2 hours (implementation + tests).
**Risk:** Low.

### Option 2: Widen the `session_token` key-name pattern to a broader credential-keyword list (`token`, `api_key`, `apikey`, `secret`, `password`, `passwd`, `pwd`, `key`)

**Approach:** Extend the regex alternation to include bare/common credential key names, accepting a higher false-positive rate on the entropy-independent path.

**Pros:** Closes the key-name gap directly.
**Cons:** Broader matching could redact non-secret short values that happen to share a key name (e.g. a UI label `"key": "dashboard"`); needs care with word-boundary and false-positive tuning.
**Effort:** 2-3 hours (implementation + false-positive tuning + tests).
**Risk:** Medium (false-positive risk on the redaction side is lower-stakes than false-negative, but still needs validation against a realistic corpus).

### Option 3: Lower `_HIGH_ENTROPY_THRESHOLD` to something below 4.0 to let the entropy fallback catch hex, while accepting a higher false-positive rate on natural-language text

**Approach:** Empirically re-tune the threshold using a real corpus (the module's own docstring already anticipates this as future work).

**Pros:** Addresses the hex gap without a hex-specific pattern; more general fix.
**Cons:** Requires building/measuring against a representative false-positive corpus per the module's own documented deferral; risk of over-redacting legitimate log content.
**Effort:** 4-6 hours (corpus building + tuning + validation).
**Risk:** Medium.

## Recommended Action

**To be filled during triage.** Options 1 and 2 together are the lowest-risk, most mechanical path (dedicated hex-length patterns + widened key-name allowlist) and can likely be combined into one PR. Option 3 (threshold re-tuning) is a larger, more open-ended follow-up already flagged as deferred work in the module itself — consider tracking separately.

## Technical Details

**Affected files:**
- `src/backlink_publisher/events/scrubber.py` — `_PATTERNS`, `_HIGH_ENTROPY_THRESHOLD`, `_HIGH_ENTROPY_MIN_LEN`
- Callers relying on this guarantee: `src/backlink_publisher/cli/_bind/chrome_backend.py`, `src/backlink_publisher/cli/admin/bind_channel.py`, `src/backlink_publisher/cli/_bind/_driver_impl.py` (all three added in D3), plus the pre-existing `src/backlink_publisher/events/_project_reducers.py:316,424`.

**Related components:** `debt_registry.toml`'s D3 entries reference `scrub_text()` as the safety mechanism for several "resolved" classifications — those classifications remain correct in that they call the function, but the function's own coverage should be tightened.

## Resources

- Discovered by: `ce-code-review mode:autofix` run `20260706-140906-a92c9d99` (adversarial reviewer), 2026-07-06, reviewing `docs/plans/2026-07-06-002-opt-hidden-debt-hardening-sweep-plan.md`'s D3 unit.
- Related plan: `docs/plans/2026-07-06-002-opt-hidden-debt-hardening-sweep-plan.md` (Sprint D, Unit D3).

## Acceptance Criteria

- [ ] A 32/40/48-char hex-encoded token embedded in an otherwise-plain-text exception message is redacted by `scrub_text()`.
- [ ] A bare `token=`, `api_key=`, or `secret=` key-value pair with a short (<32 char) value is redacted (or a documented decision is made that this is out of scope, with rationale).
- [ ] Existing `scrub_text()` tests (if any) continue to pass; new tests added for the fixed gaps.
- [ ] No regression in false-positive rate beyond what the module's own docstring targets (<=5%).

## Work Log

### 2026-07-06 - Initial Discovery

**By:** Claude Code (ce-code-review adversarial persona, orchestrator synthesis)

**Actions:**
- Verified the hex-entropy-impossibility claim mathematically (log2(16)=4.0 < 4.5 threshold).
- Verified the session_token key-name pattern's fixed allowlist by reading the regex directly.
- Confirmed this function is shared infrastructure used beyond D3's new call sites.

**Learnings:**
- The module's own docstring already anticipated threshold tuning as future work; the hex-specific mathematical impossibility is a sharper, previously-unstated finding worth acting on independently of general threshold tuning.

---

## Notes

- Not a regression introduced by this diff — `scrub_text()` predates D3. Flagged because D3 newly makes this function's correctness load-bearing for three new credential-adjacent call sites.
- Low urgency for the currently-known reachable call sites (D3's fixes are still a net improvement over the pre-fix state), but should be prioritized before this function is relied upon more broadly.
