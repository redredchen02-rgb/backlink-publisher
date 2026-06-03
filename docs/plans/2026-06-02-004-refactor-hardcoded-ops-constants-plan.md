---
title: "refactor: Env-var overrides for hardcoded ops constants"
type: refactor
status: completed
date: 2026-06-02
claims: {}
---

# refactor: Env-var overrides for hardcoded ops constants

## Overview

Operators currently cannot tune throttle delays, network parameters, or rate-limit thresholds without editing source code. This refactor adds env-var override getters for the highest-impact hardcoded constants, following the established `circuit.py` pattern. No new TOML sections are introduced — env vars keep the footprint small and avoid the `save_config` silent-drop risk.

## Problem Frame

Three classes of hardcoded values exist in the codebase:

1. **Inline magic numbers** — unnamed integers living inside function bodies (e.g., `retry_delay = 300` in `scheduler.py`) with no named constant at all.
2. **Named module constants without env override** — `_POST_PUBLISH_DELAY_S = 30` exists in 12 adapters as a named constant but cannot be overridden without a code change.
3. **Named module constants in shared networking modules** — `REQUEST_TIMEOUT = 10` in `linkcheck/http.py`, five constants in `content/fetch.py` — already named but not env-overridable.

Operators tuning publish throughput, running in slow-network environments, or debugging throttle behavior must currently touch source files.

**Out of scope (intentionally excluded):**
- Per-adapter `_HTTP_TIMEOUT_S` — intentionally divergent per platform (memory: `adapter-dedup-is-intentional-divergence`); unifying would break adapters like `instant_web.py` (3 s), `telegraph_api.py` (15 s).
- Velog `_VELOG_DAILY_CAP_PROD` — the comment "change via PR, diff = audit trail" is a deliberate policy from R18; env override would bypass the audit trail.
- API endpoint URLs (e.g., `DEVTO_ARTICLES_API`) — correct, not ops-tunable.
- Platform name strings — structural, not config.
- New `[network]` config.toml section — scope too large; risks `save_config` silent-drop.

## Requirements Trace

- R1. Operators can tune per-adapter post-publish delays without code change.
- R2. Operators can tune Velog jitter window without code change.
- R3. Operators can tune `linkcheck` and `content/fetch` network parameters without code change.
- R4. All new env vars follow existing naming convention and have validated fallback.
- R5. Inline magic numbers in WebUI are promoted to named module constants.
- R6. All new env vars are documented in `AGENTS.md`.

## Scope Boundaries

- No new config.toml sections.
- No changes to `save_config` or config loader.
- No changes to `_HTTP_TIMEOUT_S` per-adapter (intentional divergence).
- No env override for `_VELOG_DAILY_CAP_PROD` (R18 audit-trail policy).
- No changes to API endpoint URL constants.

## Context & Research

### Relevant Code and Patterns

**Canonical pattern** — `src/backlink_publisher/publishing/reliability/circuit.py`:

```python
_DEFAULT_COOLDOWN_S: int = 300

def _cooldown_s() -> int:
    try:
        return int(os.environ.get("BACKLINK_PUBLISHER_CIRCUIT_COOLDOWN_S", _DEFAULT_COOLDOWN_S))
    except (ValueError, TypeError):
        return _DEFAULT_COOLDOWN_S
```

Use this exact shape: named default constant → getter function → `try/except (ValueError, TypeError)` fallback. This pattern is established in `BACKLINK_FETCH_CACHE_MAX_ENTRIES` (in `content/fetch.py`). Note: `MEDIUM_THROTTLE_MIN/MAX` in `cli/_publish_helpers.py` uses a similar env var naming convention but lacks `try/except` — an operator setting `MEDIUM_THROTTLE_MIN=abc` still crashes. The new getters in this plan are strictly safer.

**Naming convention** (inferred from existing env vars):
- Platform-specific: no prefix — `MEDIUM_THROTTLE_MIN`, `MEDIUM_THROTTLE_MAX` → follow with `DEVTO_PUBLISH_DELAY_S`, `VELOG_THROTTLE_MIN_S`, etc.
- Framework/network-level: `BACKLINK_` prefix — `BACKLINK_FETCH_CACHE_MAX_ENTRIES` → follow with `BACKLINK_LINKCHECK_*`, `BACKLINK_FETCH_*`.

**Adapter files with `_POST_PUBLISH_DELAY_S`** (12 total):
`devto_api.py`, `hashnode_graphql.py`, `hatena_atompub.py`, `linkedin_api.py`, `notion_api.py`, `qiita_api.py`, `rentry_api.py`, `substack_api.py`, `tumblr_api.py`, `wordpresscom_api.py`, `writeas_api.py`, `zenn_github.py`

Note: `medium_api.py` and `medium_browser.py` each have two bare `30` literals at `post_publish_delay_seconds=30` keyword argument sites (no module constant). Both are included in U2's scope to close the visible inconsistency with the existing `MEDIUM_THROTTLE_MIN/MAX` env overrides. Env keys: `MEDIUM_PUBLISH_DELAY_S` (shared by both — they represent the same platform's publish timing).

**Critical: adapters use `AdapterResult` field, not `time.sleep()` directly.** The constant is used as: (1) the class-level `post_publish_delay_seconds: int = _POST_PUBLISH_DELAY_S` default attribute, and (2) an explicit `AdapterResult(..., post_publish_delay_seconds=_POST_PUBLISH_DELAY_S)` keyword arg in the publish return path. The actual `time.sleep` is executed downstream in `_engine.py:304` and `_resume.py:442` by reading `result.post_publish_delay_seconds`. U2 must update both call sites per adapter.

**Velog jitter constants** — `src/backlink_publisher/publishing/adapters/velog_graphql.py`:

```python
_VELOG_JITTER_MIN_S: int = 60
_VELOG_JITTER_MAX_S: int = 180
```

**linkcheck constants** — `src/backlink_publisher/linkcheck/http.py:18-22`:

```
REQUEST_TIMEOUT = 10, MAX_CONCURRENT = 10, MAX_RETRIES = 2, RETRY_DELAY = 1
```

Note: `RETRY_DELAY` is a **linear backoff multiplier** at `http.py:84`: `time.sleep(RETRY_DELAY * (attempt + 1))`. The env var will be named `BACKLINK_LINKCHECK_RETRY_DELAY_BASE_S` to communicate this semantics.

**content/fetch constants** — `src/backlink_publisher/content/fetch.py`:

```
FETCH_TIMEOUT = 10, MAX_RETRIES = 2, HEAD_SCAN_BYTES = 256_000,
MAX_BODY_BYTES = 1_000_000, BODY_TOO_SMALL_BYTES = 2048
```

`BACKLINK_FETCH_CACHE_MAX_ENTRIES` already env-overridable — follow that pattern.

**Inline magic numbers** — `webui_app/scheduler.py:72`: `retry_delay = 300` (unnamed, inside method body); `webui_app/routes/equity_ledger.py:72-74`: `stale_days = 30` (two independent fallbacks with duplicated try/except guard — `_resolve_stale_days()` helper already exists but the recheck handler duplicates it inline).

### Institutional Learnings

- `docs/solutions/logic-errors/save-config-write-paths-bypass-preservation-2026-05-15.md` — Do not expand `save_config`. Use env vars; never write new TOML sections.
- `docs/solutions/test-failures/ci-test-isolation-failures-medium-brave-sleep-timeout-2026-05-13.md` — Tests covering throttle/sleep constants must mock `time.sleep` at the module-level reference; patch target is `backlink_publisher.<module>.time.sleep`.
- `docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md` — Always use `monkeypatch.setenv` / `monkeypatch.delenv` in tests, never `del os.environ[...]`.

## Key Technical Decisions

- **Getter function, not inline `os.environ.get()`**: Inline reads are not testable in isolation; a named getter can be patched and audited. Matches circuit.py precedent.
- **Separate default constant + getter**: Keeps the default readable in the diff without opening the getter body. Pattern: `_DEFAULT_DEVTO_PUBLISH_DELAY_S = 30` + `_post_publish_delay_s()`.
- **No env var for `_VELOG_DAILY_CAP_PROD`**: The R18 policy ("change via PR, diff = audit trail") is intentional. Adding an env override would silently bypass the cap in production.
- **`try/except (ValueError, TypeError)` fallback**: Operator setting `DEVTO_PUBLISH_DELAY_S=abc` should not crash; fall back to default silently. Same as circuit.py.
- **RETRY_DELAY renamed to RETRY_DELAY_BASE_S**: The constant is a linear backoff multiplier (`sleep(base * attempt)`), not a flat delay. Naming must communicate semantics to operators.
- **Mandatory SLOC ceiling raise for content/fetch.py**: Current measured SLOC is 219 (not 204 — the 204 figure in `monolith_budget.toml` rationale is historical). Adding ~25 lines of getter code: 219 + 25 = ~244, which already exceeds the current ceiling of 240. The raise to 250 is mandatory in this PR, not pre-emptive.
- **No single `NetworkConfig` dataclass**: Premature unification. Add env overrides per-module; consolidation is a later cleanup if demand emerges.

## Open Questions

### Resolved During Planning

- **Should Velog daily cap get an env override?** No — R18 comment explicitly says "change via PR, diff = audit trail". Jitter only.
- **Should per-adapter `_HTTP_TIMEOUT_S` be unified?** No — values are intentionally divergent (3 s for instant_web, 15 s for telegraph, 30 s for most).
- **env var prefix convention?** Platform-specific → no prefix (follows `MEDIUM_THROTTLE_MIN` precedent). Network framework → `BACKLINK_` prefix (follows `BACKLINK_FETCH_CACHE_MAX_ENTRIES` precedent).
- **Does setting delay to 0 break anything?** Not a crash, but it collapses the downstream `> 0` verification window gate in `_engine.py` and prevents the Medium throttle adjacency guard. Valid operator choice in test environments; must be documented.

### Deferred to Implementation

- Exact test parametrize strategy for 13 adapters (one file, parametrize over adapter modules, or per-adapter).
- Whether `content/fetch.py` constants should be renamed to `_DEFAULT_*` or whether the existing public names are kept alongside the getter defaults. Recommend keeping the existing names as defaults (they may be imported by test mocks — see `content-fetch-module-global-patch-coupling` memory).

## Implementation Units

```
U1 (inline → named constants)
U2 (per-adapter AdapterResult delay env)   ──► U5 (AGENTS.md)
U3 (velog jitter env)                      ──►
U4 (network module env + SLOC bump)        ──►
```

U2, U3, U4 are fully independent of each other. U5 depends on all three.

---

- [ ] **Unit 1: Promote unnamed inline magic numbers to named module constants**

**Goal:** Eliminate unnamed integer literals inside function bodies. No env override needed — just naming and deduplication.

**Requirements:** R5

**Dependencies:** None

**Files:**
- Modify: `webui_app/scheduler.py`
- Modify: `webui_app/routes/equity_ledger.py`
- Test: `tests/webui/test_scheduler_constants.py` (new)

**Approach:**
- `scheduler.py`: add `_RATE_LIMIT_RETRY_DELAY_S: int = 300` at module level; replace `retry_delay = 300` with the constant.
- `equity_ledger.py`: add `_STALE_DAYS_DEFAULT: int = 30` at module level; replace both `30` fallback literals with the constant. Additionally, the recheck handler duplicates the try/except + `<= 0` guard inline. Do NOT call `_resolve_stale_days(data.get('stale_days'))` — that function takes zero arguments and reads from `request.args`, while the recheck handler reads from the JSON body. Instead, replace the four bare `30` literals in the recheck handler with `_STALE_DAYS_DEFAULT` directly.
- No behavioral change.

**Patterns to follow:**
- `src/backlink_publisher/publishing/reliability/circuit.py` module-level constant naming style.

**Test scenarios:**
- Happy path: `_RATE_LIMIT_RETRY_DELAY_S == 300` and is used as `retry_delay` in the 429 branch.
- Happy path: `_STALE_DAYS_DEFAULT == 30` and both `equity_ledger.py` paths use it (directly or via `_resolve_stale_days`).
- Edge case: Non-integer `stale_days` in recheck request body falls back to `_STALE_DAYS_DEFAULT` (both paths now share `_resolve_stale_days` so one test covers both).
- Edge case: `stale_days <= 0` in request body clamps to `_STALE_DAYS_DEFAULT`.

**Verification:**
- `grep -n "retry_delay = 300" webui_app/scheduler.py` returns no results.
- `grep -n "stale_days.*= 30\b\|= 30.*stale" webui_app/routes/equity_ledger.py` returns no results.

---

- [ ] **Unit 2: Add env-var override getters for per-adapter post-publish delays**

**Goal:** All 14 API-tier adapters expose their post-publish delay as an env-overridable getter. The value flows into `AdapterResult.post_publish_delay_seconds`, consumed by `_engine.py` and `_resume.py`.

**Requirements:** R1, R4

**Dependencies:** None (independent of U1)

**Files:**
- Modify: `src/backlink_publisher/publishing/adapters/devto_api.py`
- Modify: `src/backlink_publisher/publishing/adapters/hashnode_graphql.py`
- Modify: `src/backlink_publisher/publishing/adapters/hatena_atompub.py`
- Modify: `src/backlink_publisher/publishing/adapters/linkedin_api.py`
- Modify: `src/backlink_publisher/publishing/adapters/medium_api.py`
- Modify: `src/backlink_publisher/publishing/adapters/medium_browser.py`
- Modify: `src/backlink_publisher/publishing/adapters/notion_api.py`
- Modify: `src/backlink_publisher/publishing/adapters/qiita_api.py`
- Modify: `src/backlink_publisher/publishing/adapters/rentry_api.py`
- Modify: `src/backlink_publisher/publishing/adapters/substack_api.py`
- Modify: `src/backlink_publisher/publishing/adapters/tumblr_api.py`
- Modify: `src/backlink_publisher/publishing/adapters/wordpresscom_api.py`
- Modify: `src/backlink_publisher/publishing/adapters/writeas_api.py`
- Modify: `src/backlink_publisher/publishing/adapters/zenn_github.py`
- Test: `tests/publishing/test_adapter_publish_delay_env.py` (new)

**Approach:**
- In each adapter: rename `_POST_PUBLISH_DELAY_S` → `_DEFAULT_POST_PUBLISH_DELAY_S`. Add getter `_post_publish_delay_s()` following the circuit.py getter shape. Env key: `<PLATFORM>_PUBLISH_DELAY_S`.
- **The operative call site is the `AdapterResult(...)` constructor kwarg** — `_engine.py:304` and `_resume.py:442` read `result.post_publish_delay_seconds` from the AdapterResult instance, not from the adapter class:
  1. Class-level attribute (`post_publish_delay_seconds: int = _POST_PUBLISH_DELAY_S` on the Publisher subclass): rename constant to `_DEFAULT_POST_PUBLISH_DELAY_S` only — documentation-only. Do NOT call the getter here. Publisher subclasses are NOT `@dataclass`-decorated; `field(default_factory=...)` is inapplicable and would TypeError. Even if the getter were called at class level, it evaluates once at import time, not per-publish. This attribute is dead code for downstream consumers.
  2. `AdapterResult(...)` constructor keyword arg (the operative site): `post_publish_delay_seconds=_DEFAULT_POST_PUBLISH_DELAY_S` → `post_publish_delay_seconds=_post_publish_delay_s()`.
- **zenn_github.py and qiita_api.py behavior fix required**: These two adapters have a class-level attr but NO `AdapterResult(...)` constructor kwarg for `post_publish_delay_seconds`. As a result, `_engine.py` currently reads 0 (the AdapterResult default) for both — the intended 30s (zenn) and 5s (qiita) delays are silently dropped today. Adding `post_publish_delay_seconds=_post_publish_delay_s()` to their AdapterResult constructor is a behavior change (0s → 5s or 30s delay added). Flag this explicitly in the PR description.
- Each `_DEFAULT_*` constant carries a one-line comment noting the empirical or policy basis (e.g., `# LinkedIn 429s observed at < 30 s; 60 s is conservative safe floor`). Operators need signal for safe lower bounds when overriding.
- Do not change `_HTTP_TIMEOUT_S` in any adapter.

**Execution note:** All 14 adapters follow a mechanical, identical change. Use a single parametrized test file.

**Technical design** *(directional guidance, not specification)*:

```
# Before:
_POST_PUBLISH_DELAY_S = 30

# After:
_DEFAULT_POST_PUBLISH_DELAY_S = 30  # <empirical note>

def _post_publish_delay_s() -> int:
    try:
        return int(os.environ.get("DEVTO_PUBLISH_DELAY_S", _DEFAULT_POST_PUBLISH_DELAY_S))
    except (ValueError, TypeError):
        return _DEFAULT_POST_PUBLISH_DELAY_S

# Both sites updated:
post_publish_delay_seconds=_post_publish_delay_s()
```

**Patterns to follow:**
- `circuit.py:_cooldown_s()` getter — exact shape.
- `cli/_publish_helpers.py` — `MEDIUM_THROTTLE_MIN/MAX` naming precedent.

**Test scenarios:**
- Happy path: default value returned when env var not set (parametrize over all 14 platforms).
- Happy path: `DEVTO_PUBLISH_DELAY_S=5` → `_post_publish_delay_s()` returns `5`.
- Happy path: `DEVTO_PUBLISH_DELAY_S=0` → returns `0`. (Zero is valid — operator opts out of delay. Downstream `> 0` gate in `_engine.py` collapses the verify window; see System-Wide Impact.)
- Edge case: `DEVTO_PUBLISH_DELAY_S=abc` → falls back to `_DEFAULT_POST_PUBLISH_DELAY_S`, no exception raised.
- Integration: `AdapterResult.post_publish_delay_seconds` reflects the getter's return value, not the baked-in constant. (Set `DEVTO_PUBLISH_DELAY_S=5`, invoke the adapter's publish path with a mock HTTP layer, assert `AdapterResult.post_publish_delay_seconds == 5`.)
- Integration (zenn/qiita behavior fix): With env var unset, zenn returns `AdapterResult.post_publish_delay_seconds == 30` and qiita returns `5` — confirming the constructor kwarg was added and defaults were not dropped to 0.

**Verification:**
- `grep -rn "_POST_PUBLISH_DELAY_S\b" src/backlink_publisher/publishing/adapters/` returns only `_DEFAULT_*` constant declarations, no bare references.
- `grep -rn "post_publish_delay_seconds.*_DEFAULT_" src/backlink_publisher/publishing/adapters/` returns no results (all constructor usages call the getter).
- All 14 adapters have `def _post_publish_delay_s()`.

---

- [ ] **Unit 3: Add env-var override getters for Velog jitter window**

**Goal:** Velog throttle jitter band is overridable via env without touching the R18-protected daily cap.

**Requirements:** R2, R4

**Dependencies:** None (independent of U1, U2)

**Files:**
- Modify: `src/backlink_publisher/publishing/adapters/velog_graphql.py`
- Test: `tests/publishing/test_velog_jitter_env.py` (new or extend existing Velog tests)
- Modify: `tests/test_manifest_drift.py` (update drift binding to use getter return value, not bare module constant)

**Approach:**
- Add `_velog_jitter_min_s()` and `_velog_jitter_max_s()` getters using env keys `VELOG_THROTTLE_MIN_S` and `VELOG_THROTTLE_MAX_S`.
- Validation: resolve both env vars, then check `min > max`. If so, log a warning and fall back to defaults for **both**. When `min == max`, `random.uniform(a, a)` always returns `a` — this is valid deterministic behavior (operator intentionally setting fixed wait); allow it. The guard targets only strict inversion (`min > max`) where the range silently reverses.
- `_VELOG_DAILY_CAP_PROD` and `UNLOCK_DATE_UTC` are NOT touched.

**Patterns to follow:**
- `circuit.py:_cooldown_s()`.

**Test scenarios:**
- Happy path: no env set → defaults (60, 180) returned.
- Happy path: `VELOG_THROTTLE_MIN_S=30`, `VELOG_THROTTLE_MAX_S=90` → (30, 90).
- Edge case: `VELOG_THROTTLE_MIN_S=200`, `VELOG_THROTTLE_MAX_S=100` (min > max, inverted range) → falls back to (60, 180). Assert no exception AND defaults used (not the inverted range [100, 200] which `random.uniform` would silently produce).
- Edge case: `VELOG_THROTTLE_MIN_S=60`, `VELOG_THROTTLE_MAX_S=60` (min == max) → returns (60, 60). `random.uniform(60, 60)` returns 60.0; this is valid deterministic behavior, NOT a fallback case.
- Edge case: `VELOG_THROTTLE_MIN_S=abc` → min falls back to default 60; MAX unset → 180.

**Verification:**
- `grep -n "random.uniform" velog_graphql.py` calls only the getter pair, never the bare module constants.

---

- [ ] **Unit 4: Add env-var override getters for linkcheck and content/fetch network constants**

**Goal:** `linkcheck/http.py` and `content/fetch.py` module-level constants are env-overridable, consistent with `BACKLINK_FETCH_CACHE_MAX_ENTRIES`. Content/fetch SLOC ceiling pre-emptively raised.

**Requirements:** R3, R4

**Dependencies:** None (independent of U1–U3)

**Files:**
- Modify: `src/backlink_publisher/linkcheck/http.py`
- Modify: `src/backlink_publisher/content/fetch.py`
- Modify: `src/backlink_publisher/cli/_publish_helpers.py` (update by-value import of MAX_CONCURRENT)
- Modify: `monolith_budget.toml` (raise content/fetch.py ceiling 240 → 250)
- Test: `tests/linkcheck/test_linkcheck_env_overrides.py` (new)
- Test: `tests/content/test_fetch_env_overrides.py` (new or extend existing)

**Approach:**

*`linkcheck/http.py`*: Rename all four module constants to `_DEFAULT_*` (public names become `_DEFAULT_REQUEST_TIMEOUT`, etc.). Add four getters:
- `BACKLINK_LINKCHECK_REQUEST_TIMEOUT` → `_request_timeout()` — used at two sites: HEAD request (line 44), GET fallback (line 55)
- `BACKLINK_LINKCHECK_MAX_CONCURRENT` → `_max_concurrent()` — used in `check_urls` semaphore
- `BACKLINK_LINKCHECK_MAX_RETRIES` → `_max_retries()` — used in retry loop (line 75)
- `BACKLINK_LINKCHECK_RETRY_DELAY_BASE_S` → `_retry_delay_base_s()` — used as `sleep(base * (attempt + 1))` at line 84; the `_BASE_` suffix signals it is a multiplier, not a flat delay

Keep `ACCEPTABLE_CODES` as a plain constant.

*`_publish_helpers.py`*: Line 21 imports `MAX_CONCURRENT` by value (`from backlink_publisher.linkcheck.http import MAX_CONCURRENT as _LINKCHECK_MAX_CONCURRENT`). This frozen integer binding is not updated by the getter. Change the import to reference the getter function: `from backlink_publisher.linkcheck.http import _max_concurrent as _linkcheck_max_concurrent_fn` and update line 114 to call `_linkcheck_max_concurrent_fn()` instead of the frozen constant.

*`content/fetch.py`*: Keep existing public constant names in place (e.g., `FETCH_TIMEOUT`, `MAX_BODY_BYTES`) — tests import and monkeypatch them by name (per `content-fetch-module-global-patch-coupling` memory). Add five getters alongside (not replacing) the existing constants, using those constants as default values:
- `BACKLINK_FETCH_TIMEOUT` → `_fetch_timeout()` — used at line 211 (default for `timeout_seconds=None`)
- `BACKLINK_FETCH_MAX_RETRIES` → `_max_retries()` — used in retry loop (line 336)
- `BACKLINK_FETCH_HEAD_SCAN_BYTES` → `_head_scan_bytes()` — used in `_check_once` at line 246
- `BACKLINK_FETCH_MAX_BODY_BYTES` → `_max_body_bytes()` — used in body cap
- `BACKLINK_FETCH_BODY_TOO_SMALL` → `_body_too_small_bytes()` — used in `_check_once` at line 258

Keep existing public constant names in place (they may be imported by test mocks per `content-fetch-module-global-patch-coupling` memory). Getters reference those constants as defaults.

*`monolith_budget.toml`*: Raise `content/fetch.py` ceiling from 240 → 250 in the **same commit** that adds the getter functions. Update the rationale string to cite this PR (must be ≥80 chars); the existing rationale references SLOC 204 and ceiling 240, which will be factually wrong after this change. New rationale example: "Added env-var getter functions for BACKLINK_FETCH_* (5 constants × ~5 SLOC each = ~25 SLOC). Measured SLOC grew from 204 to 219 since prior rationale; ceiling raised 240→250 to accommodate getters and future modifications."

**Patterns to follow:**
- `content/fetch.py:141` — `BACKLINK_FETCH_CACHE_MAX_ENTRIES` getter (directly follow this).

**Test scenarios:**
- Happy path: no env set → constants return their defaults (parametrize over all 9 keys — 4 linkcheck + 5 fetch).
- Happy path: `BACKLINK_LINKCHECK_REQUEST_TIMEOUT=20` → `_request_timeout()` returns `20`.
- Happy path: `BACKLINK_FETCH_TIMEOUT=15` → `_fetch_timeout()` returns `15`.
- Happy path: `BACKLINK_FETCH_MAX_RETRIES=0` → returns `0` (zero is valid; `range(0+1)` = one attempt, no retry).
- Happy path: `BACKLINK_LINKCHECK_RETRY_DELAY_BASE_S=5` → `_retry_delay_base_s()` returns `5`. Verify multiplier semantics: `sleep(5 * 2)` = 10 s on second attempt, not a flat 5 s.
- Edge case: `BACKLINK_LINKCHECK_MAX_CONCURRENT=abc` → falls back to `_DEFAULT_MAX_CONCURRENT` (10).
- Integration: `check_urls()` passes `_request_timeout()` result as the `urlopen` timeout — mock verifies the env-overridden value reaches the HTTP call site.

**Verification:**
- `grep -n "REQUEST_TIMEOUT\b\|MAX_CONCURRENT\b\|MAX_RETRIES\b\|RETRY_DELAY\b" linkcheck/http.py` shows only `_DEFAULT_*` declarations; no bare constant names in function bodies.
- `python -m radon raw -s src/backlink_publisher/content/fetch.py` returns SLOC ≤ 250.
- `monolith_budget.toml` ceiling for `content/fetch.py` equals 250.

---

- [ ] **Unit 5: Document all new env vars in AGENTS.md**

**Goal:** Operators can discover all tunable env vars in one place.

**Requirements:** R6

**Dependencies:** U2, U3, U4 (document what they add)

**Files:**
- Modify: `backlink-publisher/AGENTS.md`

**Approach:**
- Locate the existing env var table in AGENTS.md.
- Add rows for: U2 (13 platform `_PUBLISH_DELAY_S` keys), U3 (2 Velog jitter keys), U4 (4 linkcheck + 5 fetch keys = 9 keys).
- Each row: key, default, description. Follow existing row format.
- The `MEDIUM_PUBLISH_DELAY_S`, `DEVTO_PUBLISH_DELAY_S`, `LINKEDIN_PUBLISH_DELAY_S` entries must note the downstream `> 0` gate: "Setting to 0 collapses post-publish link verification window from 30 s to 10 s."
- `BACKLINK_LINKCHECK_RETRY_DELAY_BASE_S` description: "Base delay for linear backoff; actual sleep = base × attempt_number."

**Test expectation:** none — documentation-only change.

**Verification:**
- `grep -c "PUBLISH_DELAY_S\|VELOG_THROTTLE\|BACKLINK_LINKCHECK\|BACKLINK_FETCH_TIMEOUT" AGENTS.md` returns ≥ 24.

---

## System-Wide Impact

- **Interaction graph:** The 13 adapter changes surface via `AdapterResult.post_publish_delay_seconds`. Downstream consumers `_engine.py:304` and `_resume.py:442` read this field with a `> 0` boolean gate: values > 0 use a 30 s post-publish verify window; value == 0 uses 10 s and suppresses the Medium throttle adjacency guard. Operators setting any delay to 0 via env are making a deliberate choice with these side effects.
- **Error propagation:** Invalid env var values fall back silently to defaults — no new exception surfaces. The try/except pattern matches circuit.py.
- **State lifecycle risks:** The getters read `os.environ` at call time (not import time). In the long-running WebUI process, an operator changing an env var after startup will affect subsequent publishes but not in-flight ones.
- **API surface parity:** `velog_graphql.py` change does not alter `UNLOCK_DATE_UTC` or `_VELOG_DAILY_CAP_PROD`.
- **Integration coverage:** `check_urls()` and `content_fetch()` are the critical call sites; integration tests should verify the env-overridden value reaches the `urlopen`/HTTP layer.
- **Unchanged invariants:** `_HTTP_TIMEOUT_S` in all adapters stays hardcoded. `_VELOG_DAILY_CAP_PROD` stays hardcoded. `save_config` is not touched.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `content/fetch.py` measured 219 SLOC; adding ~25 getter lines = ~244, which exceeds current ceiling of 240 | Raise ceiling to 250 in same PR — this is mandatory, not pre-emptive; update `monolith_budget.toml` rationale string to cite this PR (≥80 chars) |
| U2: only patching one of two call sites per adapter → `AdapterResult.post_publish_delay_seconds` carries stale constant value | Approach explicitly requires both: class-level default attribute AND `AdapterResult(...)` constructor kwarg |
| Velog min ≥ max after env override → silent inverted-range sleep (no crash, just wrong behavior) | U3 adds `min >= max` guard with explicit fallback to defaults; test asserts default values used, not absence of exception |
| Operator sets delay to 0 → collapses verify window and Medium throttle gate | Documented in System-Wide Impact and AGENTS.md |
| Test suite calls `time.sleep` with real values (CI timeout) | Mock at module-level ref; follow `docs/solutions/test-failures/ci-test-isolation-failures-medium-brave-sleep-timeout-2026-05-13.md` |
| `monkeypatch.setenv` order — later test poisons env for earlier | Always use `monkeypatch.setenv`; never `del os.environ[...]`; `_isolate_user_dirs` fixture in place |
| `content/fetch.py` test mocks patch module globals by name | Keep existing constant names; getter references them as defaults; mock targets unchanged per `content-fetch-module-global-patch-coupling` memory |
| `_publish_helpers.py` by-value import of `MAX_CONCURRENT` | Included in U4 scope; update import to use getter function reference |

## Sources & References

- Pattern file: `src/backlink_publisher/publishing/reliability/circuit.py` (getter shape)
- Existing env precedent: `src/backlink_publisher/content/fetch.py:141` (`BACKLINK_FETCH_CACHE_MAX_ENTRIES`)
- Existing env precedent: `cli/_publish_helpers.py` (`MEDIUM_THROTTLE_MIN/MAX` naming)
- Institutional: `docs/solutions/logic-errors/save-config-write-paths-bypass-preservation-2026-05-15.md`
- Institutional: `docs/solutions/test-failures/ci-test-isolation-failures-medium-brave-sleep-timeout-2026-05-13.md`
- Institutional: `docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md`
- Memory: `adapter-dedup-is-intentional-divergence` — per-adapter `_HTTP_TIMEOUT_S` divergence is intentional
- Memory: `content-fetch-module-global-patch-coupling` — keep existing constant names; test mocks patch by name
- AGENTS.md env var table — extend in U5
