---
date: 2026-05-20
topic: adapter-dofollow-gate
---

# Adapter Dofollow Gate (Capability Manifest v1 — minimal wedge)

## Problem Frame

The product's value is **dofollow backlinks**. R9's extension contract validates that a new adapter is *shaped* like an adapter (registry walks dispatch, throttle reads from `AdapterResult`, schema reads `registered_platforms()`), but it does not validate that the adapter actually produces a dofollow link. The dofollow truth lives outside the registry, in `webui_app/binding_status.py:31-58` (`_DOFOLLOW_BY_CHANNEL`), so a contributor (or automation) can ship a new platform that registers cleanly, passes the extension-readiness test, and silently emits `rel="nofollow"` content.

PR #108 → PR #109 (2026-05-20 03:29 → 03:38 UTC, 9-minute revert) made this concrete: Dev.to / Mastodon / WordPress.com landed as nofollow-only adapters and were reverted minutes later. The institutional response was a memory-feedback rule (`feedback_grep_dofollow_map_before_shipping_adapter`) — tribal knowledge that decays. We need a mechanical gate at the registration point so the same incident becomes a type/CI error, not a memory-discipline failure.

## Requirements

**Registry contract**
- R1. `publishing.registry.register(name, *adapter_cls, dofollow=, rationale=)` accepts a required `dofollow` keyword argument with three legal values: `True`, `False`, `"uncertain"`. `"uncertain"` is reserved for platforms where the dofollow attribute is unverified but the publish path is operationally functional (e.g., a future platform that publishes successfully but where rel-attr observation requires playwright fetch).
- R2. `register()` without an explicit `dofollow` kwarg is a hard error (TypeError or equivalent at import time). No default value.
- R3. `register()` with `dofollow=False` or `dofollow="uncertain"` requires an additional `rationale=` keyword argument whose value is a string with `len(rationale.strip()) >= 80`. Same pattern as `monolith_budget.toml` bumps.
- R4. `register()` with `dofollow=True` does not require `rationale=`. Passing one is allowed (informational) but not length-validated.
- R5. The registry exposes a new pure-read API: `registry.dofollow_status(name) -> Literal[True, False, "uncertain"] | None` (None = platform not registered) and `registry.dofollow_rationale(name) -> str | None`.

**Existing adapter backfill**
- R6. All currently-registered adapters must add `dofollow=` to their `register()` call in a single backfill PR alongside the gate landing.
  - Production set (`publishing/adapters/__init__.py`): blogger / medium / telegraph / velog / ghpages / writeas → `dofollow=True`; hashnode → `dofollow=False` with rationale documenting (a) GraphQL API moved behind paywall on 2026-05-13, (b) Cloudflare anti-bot blocks `*.hashnode.dev` direct fetch, (c) publish path is operationally dead today. Hashnode is degraded to `False` rather than `"uncertain"` because the platform is not just verification-blocked but ship-blocked — `"uncertain"` would misrepresent the operational reality. Future operator verification (post-CF, post-paywall) could reclassify.
  - Test fixtures that also call `register()` and must be updated in the same PR: `tests/conftest.py:213` (`_register("fake", FakeAdapter)`) and six registrations in `tests/test_publish_backlinks_banner_integration.py` (lines 145, 176, 202, 225, 256, 280: `optin_test` / `noembed_test` / `strict_test` / `permissive_test` / `nobanner_test` / `dryrun_test`).
- R7. After backfill **and** R11 negative-knowledge migration are complete, `webui_app/binding_status.py`'s `_DOFOLLOW_BY_CHANNEL` map is deleted. `get_channel_status` and `webui_app/helpers.py:_token_paste_status` both read from `registry.dofollow_status(name)` instead.

**WebUI surface preservation**
- R8. The WebUI binding card's visual contract maps each `dofollow_status` value: green badge for `True`, no badge (operator-existing styling) for `False`, orange "unverified" badge for `"uncertain"`. When `registry.dofollow_status(name)` returns `None` (platform not registered), no binding card is rendered for that name — matching today's behavior (`_DOFOLLOW_BY_CHANNEL.get(name)` returning `None` produces no badge). Per R6 the v1 platform set has no `"uncertain"` entries; the badge rule is documented for future platforms that may legitimately verify-but-not-ship-block.

**CI gate**
- R9. A new test (`tests/test_adapter_dofollow_gate.py`) asserts that for every entry in `registry.registered_platforms()`, the `dofollow_status` is set and — if `False` or `"uncertain"` — `dofollow_rationale` is a non-empty string of `len(rationale.strip()) >= 80`. The test fails CI if any registration violates the contract.
- R10. The test does not interpret rationale content; it only enforces presence and length (mirrors `monolith_budget.toml` `rationale` discipline). Rationale on `dofollow=True` is allowed but neither required nor length-validated; R4 stands.

**Negative knowledge preservation**
- R11. A new module-level `_REJECTED_PLATFORMS: dict[str, RejectionRecord]` lives alongside `_REGISTRY` in `publishing/registry.py` (or a sibling module), populated with the three reverted entries from PR #108→#109: `devto` (`rel="nofollow ugc"` since ~2022), `mastodon` (hardcoded `rel="nofollow noopener noreferrer"`), `wordpresscom` (free tier nofollow; paid tier dofollow). Each `RejectionRecord` carries `dofollow=False`, `rationale=` (≥80 chars), and `rejected_at: date`. The map is read-only at runtime — there is no `reject()` API; entries land via PR diff to the literal dict.
- R12. `register("devto", …)` (or any other name listed in `_REJECTED_PLATFORMS`) must raise `RegistryError` at import time with a message citing the prior rejection record's rationale, unless the caller passes `accept_rejection_override=True` (kw-only, intentionally awkward) to signal "I have read the prior verdict and am intentionally re-attempting." Override usage is also gated by the rationale-length rule.
- R13. The CI gate test (R9) additionally asserts no overlap between `_REGISTRY` and `_REJECTED_PLATFORMS` keys (except when `accept_rejection_override=True` was passed at registration).

## Success Criteria

- A future PR that re-introduces a nofollow platform cannot reach `main` without either: (a) `dofollow=True` (caught at runtime by an honest reviewer or by a follow-up empirical verifier), or (b) `dofollow=False` + ≥80-char rationale, OR (c) for previously-rejected platforms, an explicit `accept_rejection_override=True` + rationale citing what changed since the prior verdict.
- `webui_app/binding_status.py` has zero hand-maintained dofollow knowledge — single source of truth is `register()` call sites and `_REJECTED_PLATFORMS`.
- The current 7-platform live set ships unchanged externally: WebUI binding cards render identically except Hashnode flips from orange "unverified" to no-badge "False" (a one-time UI honest-rebadging that matches operational reality — Hashnode publish path is dead).
- Negative knowledge of devto/mastodon/wpcom rejection survives the map deletion — re-attempts at those names raise a registry-level error citing the prior verdict.
- The 9-minute revert sequence of PR #108 → #109 becomes unreproducible: the same diff would either fail the gate test (if `dofollow=False` is honest but the reviewer caught it) or fail at import time (if the names appear in `_REJECTED_PLATFORMS`).

## Scope Boundaries

- **Out of scope for v1**: `banner_upload`, `oauth_dialect`, `daily_cap`, `observed_rel_attrs`, `bindable`, and any other adapter capability beyond `dofollow`. The minimal wedge ships first; further capability fields are gathered through future PR-level pain. Acknowledged tradeoff: each new capability is a per-field backfill PR touching every existing `register()` call site (linear cost). When the second capability field becomes concrete, planning should re-evaluate whether to migrate to an `AdapterCapability` dataclass for sub-linear extension cost.
- **Out of scope**: replacing the duck-typed `embed_banner` Protocol opt-in. That contract is lazy-load-per-adapter for good reason (PR #123 ghpages config-load) and the brainstorm explicitly preserves it.
- **Out of scope**: a live web probe that auto-discovers dofollow status (round-6 rejection #5). The gate trusts the declared value; empirical re-verification is a separate, optional follow-up.
- **Out of scope**: rationale-content linting (no NLP, no "this rationale is too vague" check). Length-only, matches monolith-budget discipline.
- **Deferred to v2**: scheduled CI job that samples published URLs weekly, parses observed `rel` attribute, and alarms on declared/observed mismatch. Without this, the gate is asymmetric — defends against new lies, accepts old wrong (Medium 2023 deprecation, dev.to 2022 nofollow flip pattern). v1 ships static gate; v2 catches drift.

## Considered Alternatives

| Approach | Surface area | Defense quality | Reversal cost | Future extensibility |
|---|---|---|---|---|
| **A. Snapshot test** (`tests/test_registry_dofollow.py` asserts the dofollow=True platform list as a hardcoded literal) | 1 file, ~5 lines | Forces diff visibility of new dofollow=True entries but stores no rationale or empirical evidence; reviewer sees `+'newplatform'` but no co-located justification. No defense for `_REJECTED_PLATFORMS` semantics. | Trivial — delete one test file | Cannot extend: every capability needs its own snapshot test, and rationale lives only in PR comments (decays as PRs are squash-merged) |
| **B. register() kw-arg + rationale (CHOSEN)** | Registry signature + 7+7 backfill sites + new `_REJECTED_PLATFORMS` map + new tests + WebUI rewire | Rationale co-located with adapter code; survives squash-merge; WebUI can surface rationale; CI gate catches missing-kwarg + missing-rationale-on-False; `_REJECTED_PLATFORMS` preserves negative knowledge from prior PRs | Medium — kw-arg list can grow but each new field is per-adapter backfill | Per-capability backfill PR pattern repeats; kw-arg list grows linearly |
| **C. AdapterCapability dataclass** | Registry signature + dataclass + same backfill + adapters import a frozen class | Same as B but sub-linear future cost (default-valued fields don't force backfill) | Higher — dataclass adoption is harder to reverse | Sub-linear: new capability fields with defaults compose without backfill |

**Rationale for B over A**: rationale co-located with adapter code is the load-bearing improvement. The snapshot-test alternative achieves the same "PR diff makes new dofollow=True visible" property but throws away the field where empirical evidence lives, so future operators must re-grep PR history to understand *why* a platform was declared dofollow. The diff-visibility property is also strictly weaker — `_REJECTED_PLATFORMS` cannot exist under approach A without parallel scaffolding that re-introduces the same surface area B has.

**Rationale for B over C**: dataclass adoption is premature when only one capability field exists today. The right time to upgrade B → C is when the second capability field becomes concrete (banner_upload as standalone, or a `bindable` flag forced by a Hashnode-class situation).

## Key Decisions

- **Minimal wedge over full dataclass.** Add `dofollow` alone to `register()` solves the PR #108 incident class without paying the schema-drift tax. Migration to dataclass is a future evolution, not a v1 commitment.
- **Strict over soft.** `dofollow=` is required (no default). A default-True would re-introduce the PR #108 failure mode silently. Forcing a type error at import time is the value proposition.
- **Hashnode honest-degrade to False.** `"uncertain"` is reserved for "publishable + dofollow-unverified" — Hashnode is neither (CF + paywall block publish entirely). Honest False matches operational reality. `"uncertain"` remains a legal type-level value for future platforms that fit it cleanly.
- **CI gate enforces presence/length, not semantics.** Same discipline as `monolith_budget.toml`: machine checks the contract shape, humans review the content. Rationale-quality is a PR-review concern.
- **`_REJECTED_PLATFORMS` preserves negative knowledge.** R7 deletion would lose the deliberately-preserved devto/mastodon/wpcom verdicts from PR #108 retrospective. R11-R13 migrate the negative-knowledge corpus into a structured, runtime-enforceable registry that catches re-attempts at import time.

## Dependencies / Assumptions

- Depends on `publishing.registry.register()` signature being stable enough to extend with keyword args. Today the call sites are all inside `publishing/adapters/__init__.py` (per-package registration) — no external registrar.
- Assumes the R9 contract (`tests/test_r9_extension_readiness.py`) does not assert the *negative* — i.e., it doesn't say "register() must NOT take any keyword arg besides X". Verified: it asserts the positive (one-line extension, no CLI/schema touches).
- `_DOFOLLOW_BY_CHANNEL` has external consumers beyond `webui_app/binding_status.py`. The backfill PR must update: `webui_app/helpers.py:929` (`_token_paste_status` imports and reads the map at line 947 — undocumented second production consumer added with PR #112); `tests/test_webui_token_paste.py:176`; `tests/test_save_config_new_channel_roots.py:288`; `tests/test_settings_dashboard_rendering.py:91`; and `docs/plans/2026-05-20-003-feat-portfolio-roundtrip-spike-quality-plan.md` Phase C, which reads the map for portfolio scorecards. Migration sequence (gate first, then map deletion, then dependent-plan reads) must be planned.

## Outstanding Questions

### Resolve Before Planning
(none — product decisions complete)

### Deferred to Planning
- [Affects R1, R2][Technical] Should `dofollow` be positional or kw-only? Kw-only is safer (forces grep-friendly `dofollow=True` at every call site) but slightly more verbose. Likely kw-only.
- [Affects R6, R7, R11][Technical] Migration sequence — gate test landing dead-last so it doesn't break every commit in the stack. Atomic single-PR is preferable but commit ordering matters: (1) add `_REJECTED_PLATFORMS` infrastructure; (2) extend `register()` signature with optional `dofollow=`; (3) backfill all 7 production + 7 test sites; (4) add WebUI helpers.py + binding_status.py read-path migration; (5) delete `_DOFOLLOW_BY_CHANNEL`; (6) flip `dofollow=` from optional to required; (7) land the CI gate test.
- [Affects R5][Needs research] Should `dofollow_status` / `dofollow_rationale` be module-level functions or attributes on a `RegistryEntry` dataclass? Today `_REGISTRY` is `dict[str, list[type[Publisher]]]`. The recommended v1 shape is parallel-dict (`_DOFOLLOW_BY_PLATFORM: dict[str, Literal[True, False, "uncertain"]]` and `_RATIONALE_BY_PLATFORM: dict[str, str]`) — keeps `_REGISTRY` value type unchanged so the conftest snapshot/restore fixture at `tests/conftest.py:212-220` survives. Migration to a `RegistryEntry` dataclass deferred to capability field #2.
- [Affects R9][Technical] Where does the gate test live: `tests/test_adapter_dofollow_gate.py` (new file, mirrors `test_r9_extension_readiness.py`) or extended into the existing R9 test? Planning chooses based on test-grouping conventions.
- [Affects R12][Technical] Should `RegistryError` for rejected-platform re-attempt be a new exception class or reuse an existing one? `_util/errors.py` review needed.

## Residual concerns (raised in document review, accepted as planning-stage)

- Rationale length-only enforcement is anti-correlated with truth (5-char honest fact rejected, 80-char filler accepted). Mitigation: PR review remains the human content gate; CI enforces presence/length only. Worst-case adversary (ceremonial filler) is no worse than today's no-gate baseline.
- Hashnode UI badge change (orange → no-badge False) is a one-time visual delta that should be called out in the PR description so operators don't perceive it as a regression.

## Next Steps
→ `/ce:plan` for structured implementation planning


## Outcome (2026-06-01)

Shipped → `docs/plans/2026-05-20-009-feat-adapter-dofollow-gate-plan.md` (status: completed).