---
title: "refactor: Adapter Config Standardization and Env-Var Consolidation"
type: refactor
status: completed
date: 2026-06-03
---

# refactor: Adapter Config Standardization and Env-Var Consolidation

## Overview

Three small-blast-radius refactors shipped as independent PRs:

1. **U1** — Fix four wave-1/2 adapters that silently publish with zero post-publish delay (same class of bug plan 004 fixed for 14 adapters).
2. **U2** — Promote the two in-comment "retiring" adapters (hashnode, writeas) to a first-class `visibility="retired"` state in the registry.
3. **U3** — Introduce a `[throttle.<platform>]` unmanaged config section as an operator-editable override layer beneath env vars, following the existing "unmanaged root" pattern used by `[sites.*]`, `[anchor.proportions]`, and `[geo.probe_provider]`.

The env-var-first architecture from plan 004 is preserved: env vars remain the highest-precedence override in all three units. U3 does not move env vars — it adds a new lower-precedence layer (TOML) below them.

## Problem Frame

**Wave-1/2 delay gap (U1):** `hackmd_api.py`, `mataroa_api.py`, `notesio_api.py`, and `livejournal_api.py` return `AdapterResult` without `post_publish_delay_seconds`. The field defaults to `0.0`, so the engine publishes these platforms at full speed — the same footprint bug that plan 004 fixed for zenn and qiita.

**Phantom retirement (U2):** Hashnode and writeas carry `# retiring (PR #204)` and `# retiring (PR #202)` comments in `__init__.py` but are still `visibility` default ("active") in the registry. `registered_platforms()` still surfaces them. The planned PRs appear to not have been executed.

**Operator throttle ergonomics (U3):** Operators currently must set per-platform env vars to tune delays — useful for CI but inconvenient for long-running local operators. A `[throttle.<platform>]` TOML section that follows the same "unmanaged root / preserved verbatim" pattern would let operators configure once in `config.toml` without mutating their shell environment, while keeping env vars as the escape hatch.

## Requirements Trace

- R1. Each wave-1/2 adapter's `AdapterResult` carries a non-zero `post_publish_delay_seconds` when the env var is set.
- R2. `active_platforms()` excludes hashnode and writeas after the change; `registered_platforms()` still lists them (it returns all keys regardless of visibility — the relevant filter function is `active_platforms()`).
- R3. An operator can set `[throttle.hackmd]` (or any other platform) in `config.toml` using the `delay_s` key (e.g. `delay_s = 30.0`) and the adapter respects it without setting an env var.
- R4. A `save_config()` call must not silently drop any `[throttle.*]` entry — round-trip must be verifiable by test.
- R5. Env var always overrides TOML; TOML always overrides hardcoded default (precedence order is documented and tested).
- R6. No adapter module or test file references a deleted or retired adapter import that would silently pass (mock.patch string scan).

## Scope Boundaries

- No physical file deletion of `hashnode_graphql.py` or `writeas_api.py` — retirement is registry-only in this PR; deletion is a follow-up.
- No additions to `_FIXED_KNOWN_ROOTS` — `throttle` is intentionally absent (an unmanaged root) so `_preserve_unknown_sections` preserves it verbatim. Do not add `throttle` to this set.
- No WebUI read-path for `[throttle.*]` — this is CLI/operator-edit only; WebUI integration belongs to the "thin-WebUI" follow-up.
- No new test base class — the `conftest.py` autouse fixtures (`_isolate_user_dirs`, `_mock_check_url`, `_block_sockets`) already provide the implicit baseline for all adapter tests. Adding a separate class would be YAGNI.
- ghpages and gitlabpages adapters: verify whether they need `post_publish_delay_seconds` (git-push based, rate limits differ from REST APIs); include in U1 only if clearly warranted.
- No changes to `MEDIUM_THROTTLE_MIN/MAX` (CLI layer, plan 004 explicitly deferred these).

## Context & Research

### Relevant Code and Patterns

- **Plan 004 precedent (shipped PR #397):** `tests/test_adapter_publish_delay_env.py` — parameterized `ADAPTER_DELAY_PARAMS` list covering 14 adapters; pattern to follow exactly for U1.
- **Unmanaged root pattern:** `Config.site_url_categories`, `Config.anchor_proportions`, `Config.geo_probe_provider` in `src/backlink_publisher/config/types.py` — fields populated during parse, never written by `save_config`, preserved verbatim by `_preserve_unknown_sections`.
- **`_preserve_unknown_sections` mechanics:** `src/backlink_publisher/config/_toml_utils.py:116` — sections whose root is NOT in `known_roots` are carried verbatim; "throttle" is not in `_FIXED_KNOWN_ROOTS = {"targets", "image_gen"}` and will be preserved automatically.
- **Adapter getter shape:** `devto_api._post_publish_delay_s()` (plan 004 U2) — module-level function, `os.environ.get("DEVTO_PUBLISH_DELAY_S")` with hardcoded default, returned via `AdapterResult(post_publish_delay_seconds=...)`.
- **Lazy `load_config()` inside method:** `docs/solutions/best-practices/embed-banner-lazy-config-load-contract-2026-05-20.md` — adapter methods must call `load_config()` lazily inside the method body, never at import time or in `__init__`.
- **Registry visibility field:** `publishing/_manifest_types.py` — `Visibility = Literal["active", "experimental", "hidden", "retired"]`; retired platforms are filtered by `visibility(name) in {"hidden","retired"}` in `_registry_manifest.py`.
- **Existing retiring comments:** the `register("hashnode", ...)` and `register("writeas", ...)` calls in `__init__.py`, currently marked with inline comments `# retiring (PR #204)` and `# retiring (PR #202)` respectively.

### Institutional Learnings

- **`save_config` silent-drop trap:** `docs/solutions/logic-errors/save-config-write-paths-bypass-preservation-2026-05-15.md` — new TOML sections must be unmanaged roots or have explicit round-trip tests. U3 follows unmanaged-root path; round-trip test is mandatory in same PR.
- **`monkeypatch.setenv` rule:** `docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md` — never use `del os.environ[...]` in tests; always `monkeypatch.setenv` / `monkeypatch.delenv`.
- **Adapter mock.patch silent failure:** `docs/solutions/correctness/adapter-silent-exceptions-resolution.md` — when retiring an adapter, grep for all `mock.patch` string targets pointing at its module; residual strings silently pass without actually patching (see cnblogs_api precedent).
- **WebUI write-path exclusion:** `docs/solutions/best-practices/webui-config-request-cache-governance-2026-06-03.md` — if any WebUI handler ever reads `platform_throttle` in a follow-up, it must go through `_g_cache`; write handlers must use direct `load_config()`. Not in scope here but noted for future.

### External References

No external research required — plan 004 and the unmanaged-root pattern provide direct precedents.

## Key Technical Decisions

- **env var > TOML > hardcoded default (U3):** Preserves plan 004's architecture. Operators who already rely on env vars see no behavior change. TOML is a convenience layer for long-running local operators; CI pipelines keep using env vars.

- **Unmanaged root, not managed round-trip (U3):** `throttle` is NOT added to `_FIXED_KNOWN_ROOTS`. `_preserve_unknown_sections` carries it verbatim. This avoids requiring `save_config` to serialize all throttle keys, which would require enumerating every platform in the writer — fragile and unnecessary. Tradeoff: operators must hand-edit `config.toml`; the CLI cannot programmatically update throttle values.

- **`Config.platform_throttle: dict[str, float]` (U3):** A flat map keyed by platform slug (same slug used in `register()`), value is seconds. Populated from `[throttle.<slug>]` sections. Not written by `save_config`. This is identical in spirit to `Config.anchor_proportions`.

- **retirement = visibility change only, not file deletion (U2):** Lets the 14-adapter delay test keep its entries for hashnode and writeas (their `_post_publish_delay_s()` functions still exist). Physical deletion in a subsequent cleanup PR avoids unexpected test breaks in this PR.

- **No shared adapter test base class:** Existing conftest autouse fixtures + the parameterized `test_adapter_publish_delay_env.py` pattern provide sufficient standardization. An abstract base class would add indirection with no behavioral guarantee, violating the simplicity constraint.

## Open Questions

### Resolved During Planning

- **Is `[throttle.*]` preserved by `_preserve_unknown_sections`?** Yes — "throttle" is not in `_FIXED_KNOWN_ROOTS = {"targets", "image_gen"}`, so it is treated as an unmanaged root and carried verbatim through any `save_config()` call. Confirmed by reading `config/_toml_utils.py:19-42`.

- **Does retiring hashnode/writeas break the delay test?** No — retirement via `visibility="retired"` leaves `hashnode_graphql.py` and `writeas_api.py` in place, so their `_post_publish_delay_s()` getters remain importable. No change to `ADAPTER_DELAY_PARAMS` is required.

- **Should ghpages/gitlabpages get delay getters?** Implementer must verify: these are git-push adapters without rate limits comparable to REST APIs. If their `AdapterResult` calls already pass `post_publish_delay_seconds=0` explicitly (indicating intentional no-delay), skip them. If the field is absent (defaulting to 0), add a getter with a conservative default (~5s) and include in the parameterized test.

### Deferred to Implementation

- **Exact default values for wave-1/2 adapters:** Implementer should research each platform's documented or observed rate limits. Suggested starting points: hackmd=30s, mataroa=15s, notesio=10s, livejournal=30s — but these are directional, not binding.
- **Config parser insertion point for `[throttle.*]`:** Identify the correct parser cell or hook in `config/parsers/` that handles custom-root sections (same location as `anchor_proportions` parser). Do not modify `save_config` writer.
- **Complexity budget check for `config/types.py`:** Adding one dataclass field plus a brief docstring is typically under 5 SLOC; verify `monolith_budget.toml` ceiling is not breached.

## Implementation Units

```
U1 (wave-1/2 delay fix)   ──→   U3 (TOML throttle section)

U2 (retire hashnode/writeas)     ← independent of U1/U3
```

---

- [ ] **U1: Add `_post_publish_delay_s()` getter to wave-1/2 adapters**

**Goal:** Four wave-1/2 adapters produce non-zero `post_publish_delay_seconds` in their `AdapterResult`, controllable via env var, matching the plan 004 pattern.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `src/backlink_publisher/publishing/adapters/hackmd_api.py`
- Modify: `src/backlink_publisher/publishing/adapters/mataroa_api.py`
- Modify: `src/backlink_publisher/publishing/adapters/notesio_api.py`
- Modify: `src/backlink_publisher/publishing/adapters/livejournal_api.py`
- Verify + possibly modify: `src/backlink_publisher/publishing/adapters/ghpages.py`, `gitlabpages.py`
- Modify: `tests/test_adapter_publish_delay_env.py`

**Approach:**
- Add a module-level `_post_publish_delay_s() -> float` function to each adapter, reading `<PLATFORM>_PUBLISH_DELAY_S` env var with `int(os.environ.get(..., default))`.
- Pass `post_publish_delay_seconds=_post_publish_delay_s()` in every `AdapterResult(...)` constructor call within the adapter (some adapters call it from both publish and draft paths).
- Extend `ADAPTER_DELAY_PARAMS` in `tests/test_adapter_publish_delay_env.py` with one entry per new adapter, following the exact four-tuple `(module_path, getter_name, env_var_name, default)` shape.

**Patterns to follow:**
- `src/backlink_publisher/publishing/adapters/devto_api.py` — canonical `_post_publish_delay_s()` shape from plan 004.
- `tests/test_adapter_publish_delay_env.py:23` — `ADAPTER_DELAY_PARAMS` parameterization pattern.

**Test scenarios:**
- Happy path: for each of the 4 (or 6) adapters, `monkeypatch.setenv("<PLATFORM>_PUBLISH_DELAY_S", "99")` → `_post_publish_delay_s()` returns `99.0`.
- Edge case: env var not set → returns hardcoded default (e.g., 30 for hackmd).
- Edge case: env var set to `"0"` → returns `0.0` (no delay suppression by the getter itself).
- Integration: adapter's `AdapterResult` carries `post_publish_delay_seconds == _post_publish_delay_s()` when called with a mocked HTTP response.

**Verification:**
- `pytest tests/test_adapter_publish_delay_env.py` covers all new entries and is green.
- `grep -n "post_publish_delay" src/backlink_publisher/publishing/adapters/hackmd_api.py` shows the kwarg present in every `AdapterResult(...)` call.

---

- [ ] **U2: Retire hashnode and writeas in the adapter registry**

**Goal:** `registered_platforms()` excludes hashnode and writeas; the registry's `visibility` field for both is `"retired"` instead of the comment-only status today.

**Requirements:** R2, R6

**Dependencies:** None (independent of U1/U3)

**Files:**
- Modify: `src/backlink_publisher/publishing/adapters/__init__.py`
- Scan (no edit needed if clean): `tests/` — grep for `mock.patch` string targets containing `hashnode_graphql` or `writeas_api`
- No changes to `hashnode_graphql.py` or `writeas_api.py` source files (kept for follow-up deletion PR)

**Approach:**
- In `__init__.py`, add `visibility="retired"` keyword argument to the `register("hashnode", ...)` and `register("writeas", ...)` calls. Replace or augment the existing inline comment.
- Run `grep -rn 'mock.patch.*hashnode_graphql\|mock.patch.*writeas_api' tests/` — any match is a residual string target that must be updated or removed. The cnblogs_api precedent (solution doc) shows these silently pass without patching the right thing.
- Do NOT remove the adapters from `ADAPTER_DELAY_PARAMS` in `test_adapter_publish_delay_env.py` — the getter functions remain importable.

**Patterns to follow:**
- `__init__.py:171` — `visibility="experimental"` usage for another adapter; same keyword position in the `register()` call.
- `docs/solutions/correctness/adapter-silent-exceptions-resolution.md` — cnblogs_api mock.patch scan procedure.

**Test scenarios:**
- Happy path: after the change, `active_platforms()` does not contain `"hashnode"` or `"writeas"`; `registered_platforms()` still lists them (expected — all keys are present regardless of visibility).
- Happy path: `visibility("hashnode") == "retired"` and `visibility("writeas") == "retired"`.
- Error path: CLI `publish-backlinks --platform hashnode` (or equivalent) returns a non-zero exit code or prints an unsupported-platform message (the CLI uses `active_platforms()` for valid-platform gating).
- Regression: all currently active platforms still appear in `active_platforms()` (no accidental removal).
- No silent mock.patch residue: `grep` finds zero matches for `mock.patch.*hashnode_graphql` or `mock.patch.*writeas_api` in the test tree.

**Verification:**
- `pytest tests/test_r9_extension_readiness.py` passes (registry invariants).
- `python -c "from backlink_publisher.publishing.registry import active_platforms, visibility; assert 'hashnode' not in active_platforms(); assert visibility('hashnode') == 'retired'"` exits 0.

---

- [ ] **U3: Add `[throttle.<platform>]` unmanaged config section with adapter getter fallback**

**Goal:** An operator can set `delay_s` in `[throttle.<platform>]` in `config.toml`; the adapter's `_post_publish_delay_s()` respects it as a middle tier (env var > TOML > default); `save_config()` does not drop the section.

**Requirements:** R3, R4, R5

**Dependencies:** U1 (U3 extends the getters U1 introduces; also applies to the 14 plan-004 getters)

**Files:**
- Modify: `src/backlink_publisher/config/types.py` — add `platform_throttle: dict[str, float]` field to `Config`
- Modify: `src/backlink_publisher/config/parsers/` — parse `[throttle.*]` entries into `Config.platform_throttle` (identify the correct parser hook; follow the `anchor_proportions` or `geo_probe_provider` insertion point)
- Modify: all 18 adapter `_post_publish_delay_s()` getters (14 from plan 004 + 4 from U1) — add TOML fallback tier
- Modify: `config.example.toml` — add commented `[throttle.hackmd]` and `[throttle.devto]` examples with `delay_s` key
- Add test: `tests/test_config_throttle_round_trip.py` (new file)

**Approach:**
- `Config.platform_throttle` is a `dict[str, float]` (keyed by platform slug, value = seconds). Docstring should state "Operator-edit-only; not modeled in `Config` for rewrite. Preserved verbatim by `save_config` (unmanaged root)." — matching the `site_url_categories` docstring pattern.
- Adapter getter precedence (directional sketch — not implementation specification):
  ```
  1. os.environ.get("<PLATFORM>_PUBLISH_DELAY_S")  → if set, return float(env_val)
  2. load_config().platform_throttle.get("<slug>") → if present, return float(toml_val)
  3. return <hardcoded_default>
  ```
- The `load_config()` call inside the getter must be lazy (inside the function body, not at module scope) — per the embed-banner lazy-load contract.
- "throttle" must NOT be added to `_FIXED_KNOWN_ROOTS`. Verify `config/_toml_utils.py` does not reference it.
- `config.example.toml` example should show the slug format (lowercase, underscore-free, matching the `register()` first argument).
- **TOML schema:** `[throttle.<slug>]` sections contain a single key `delay_s` (float, seconds). The parser iterates all subsections under `throttle`, extracts `delay_s` from each, and builds `Config.platform_throttle = {slug: float(cfg["delay_s"]) for slug, cfg in data.get("throttle", {}).items() if isinstance(cfg, dict) and "delay_s" in cfg}`. Sub-tables lacking `delay_s` are skipped silently; `delay_s` present but non-numeric raises `InputValidationError`. Other keys in the sub-table are ignored.

**Patterns to follow:**
- `Config.anchor_proportions` and `Config.geo_probe_provider` in `config/types.py` — unmanaged root fields with the same docstring pattern.
- `_preserve_unknown_sections` in `config/_toml_utils.py:116` — confirms "throttle" is automatically preserved.
- `devto_api._post_publish_delay_s()` — existing getter to extend with TOML fallback.

**Test scenarios:**
- Happy path: `config.toml` contains `[throttle.hackmd]\ndelay_s = 45.0`; `load_config().platform_throttle["hackmd"]` returns `45.0`.
- Happy path: adapter getter returns TOML value when env var is unset.
- Precedence: env var set to `"20"` with `config.toml` `delay_s = 45.0` → getter returns `20.0` (env wins).
- Precedence: neither env var nor TOML present → getter returns hardcoded default.
- Round-trip (R4): write a `config.toml` with `[throttle.hackmd]\ndelay_s = 45.0` and `[targets."example.com"]` — call `save_config(...)` that writes target data — re-read the file and assert `[throttle.hackmd]` section is still present with `delay_s = 45.0`.
- Integration: `load_config()` on a `config.toml` with no `[throttle.*]` section returns `Config.platform_throttle == {}` (empty dict, no exception).
- Edge: unknown platform slug in `[throttle.unknown_slug]` → loaded into `platform_throttle` dict without error; adapter for a different platform is unaffected.

**Verification:**
- `pytest tests/test_config_throttle_round_trip.py` covers all round-trip and precedence scenarios.
- `python -c "from backlink_publisher.config._toml_utils import _FIXED_KNOWN_ROOTS; assert 'throttle' not in _FIXED_KNOWN_ROOTS"` exits 0.
- No `save_config`-related test regressions in existing suite.

## System-Wide Impact

- **Interaction graph:** `_engine.py` and `_resume.py` read `AdapterResult.post_publish_delay_seconds` to call `time.sleep`; U1 provides this value where it was previously missing. No engine changes required.
- **Error propagation:** Getter `_post_publish_delay_s()` in U3 calls `load_config()` — if config is invalid, this will raise `InputValidationError` before the publish attempt. This is acceptable (matches existing config-validation behavior) but should be tested.
- **State lifecycle risks:** `save_config` not round-tripping `[throttle.*]` is the key risk. Mitigated by using the unmanaged-root path and requiring a round-trip test in U3.
- **API surface parity:** The `platform_throttle` dict is read-only via `load_config()`. No WebUI write surface exists in this plan; if one is added later, it must follow the write-handler exclusion rule.
- **Unchanged invariants:** All 14 plan-004 getters retain env var behavior unchanged. U3 only adds a new lower-precedence tier.
- **Integration coverage:** A test that calls an adapter's publish path against a mocked HTTP response with a config containing `[throttle.platform]` would prove the lazy `load_config()` call inside the getter fires correctly; add at minimum one such integration scenario per adapter in U1.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `_preserve_unknown_sections` edge case: throttle section at end of file with no trailing newline | Confirmed `_toml_utils.py` adds trailing `\n` if output is non-empty; test with both cases |
| Adapter getter calls `load_config()` on every publish — performance if many adapters run concurrently | `load_config()` reads from disk each call; for batch publish, this is acceptable. If profiling shows it is hot, memoization belongs in a follow-up, not this PR |
| U2 retirement breaking callers that iterate `active_platforms()` and expect hashnode/writeas | Callers already filter by `active_platforms()`; retired platforms are excluded by design. `registered_platforms()` still lists them, so any test asserting they are present there continues to pass |
| Stale mock.patch strings after U2 retirement | Explicit grep scan in U2 approach; CI will not catch these silently |
| Wave-1/2 adapters pass `post_publish_delay_seconds` twice if the constructor call already provides it | Check each `AdapterResult(...)` call site for existing kwarg before adding; search `post_publish_delay_seconds` in each file first |

## Documentation / Operational Notes

- `config.example.toml` gains a `[throttle.*]` section with comments explaining env-var precedence — operators do not need to read code to understand the override ladder.
- `AGENTS.md` "env var table" should be noted as still correct (env vars remain valid); U3 supplements, does not replace.
- No migration required: existing deployments with only env vars are unaffected. TOML section is optional.

## Sources & References

- Plan 004 (predecessor): `docs/plans/2026-06-02-004-refactor-hardcoded-ops-constants-plan.md`
- save_config trap: `docs/solutions/logic-errors/save-config-write-paths-bypass-preservation-2026-05-15.md`
- Lazy load_config contract: `docs/solutions/best-practices/embed-banner-lazy-config-load-contract-2026-05-20.md`
- monkeypatch rule: `docs/solutions/test-failures/del-os-environ-poisons-session-scoped-config-dir-fixture-2026-05-27.md`
- mock.patch scan: `docs/solutions/correctness/adapter-silent-exceptions-resolution.md`
- WebUI cache governance: `docs/solutions/best-practices/webui-config-request-cache-governance-2026-06-03.md`
- Registry visibility: `src/backlink_publisher/publishing/_manifest_types.py`
- _preserve_unknown_sections: `src/backlink_publisher/config/_toml_utils.py:116`
- Existing delay test: `tests/test_adapter_publish_delay_env.py`
