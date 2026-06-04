---
title: "refactor: Remove beehiiv / cnblogs / habr / ghost channels"
type: refactor
status: completed
date: 2026-05-26
---

# refactor: Remove beehiiv / cnblogs / habr / ghost channels

## Overview

Operator has no accounts on **beehiiv**, **cnblogs (博客园)**, **habr**, and **ghost** and
cannot use them. Remove all four channels cleanly from the registry-driven publishing
pipeline so they no longer appear in `registered_platforms()`, the publish CLI, the WebUI
publish form, the dofollow/tier matrices, or token/credential handling.

The codebase is post-R9 registry-driven: argparse choices, `schema.validate_publish_payload`,
the content-tier matrix, the dofollow gate, and the WebUI platform list all read from
`publishing.registry.registered_platforms()` dynamically. Removing a channel is therefore the
reverse of the documented "1 dict + 1 register line" add recipe — delete the `register()` call
and its supporting artifacts, and every dynamic consumer updates itself. No `cli/*.py`,
`schema.py`, `webui_app/`, or `content_negotiation.py` edits are required.

Platform count: **28 → 24**.

## Problem Frame

These four adapters are dead weight for this operator: no credentials, no accounts, no intent
to use them. Two of them are also low-value link targets per their own registration evidence
(`beehiiv` ships `dofollow=False`; `habr`/`ghost`/`cnblogs` ship `dofollow="uncertain"` with no
canary). "移除干净" = full deletion (adapter modules, tests, registry entries, manifests,
rationales, token/config wiring) — **not** the soft `HIDDEN_FROM_UI` retirement pattern, since
there is no reason to keep importable-but-hidden adapters the operator can never bind.

## Requirements Trace

- R1. `registered_platforms()` no longer contains `beehiiv`, `cnblogs`, `habr`, or `ghost`.
- R2. The four adapter modules and their dedicated test modules are deleted.
- R3. No dangling imports, manifest definitions, dofollow rationales, or token/config entries
  reference the four slugs.
- R4. The full pytest suite passes (the parametrized-over-`registered_platforms()` gates —
  dofollow gate, manifest contract, content-negotiation drift — auto-shrink and stay green).
- R5. `grep -i` for the four slugs returns nothing in `src/` and active tests (excluding
  historical `docs/` and the known `ghost.png` / `HostFilter` substring false positives).

## Scope Boundaries

- **Non-goal:** touching `cli/*.py`, `schema.py`, `content_negotiation.py`, or `webui_app/` —
  all read the registry dynamically; verified to contain zero hardcoded references to the four.
- **Non-goal:** rewriting historical records. `docs/plans/2026-05-26-002-*`,
  `docs/requirements/2026-05-25-channel-expansion-plan-requirements.md`, and
  `docs/solutions/best-practices/wip-branch-ff-merge-instead-of-reset-2026-05-26.md` mention
  these channels as historical fact — leave them untouched.
- **Non-goal:** deleting on-disk credential files (`~/.config/backlink-publisher/*-token.json`,
  `*-credentials.json`). The operator has no accounts, so none should exist; if any do, removal
  is an operator step, not a code change.
- **Non-goal:** the `HIDDEN_FROM_UI` soft-retire path — this is a hard removal.

## Context & Research

### Relevant Code and Patterns

Touch points confirmed by grep (canonical `backlink-publisher/` tree):

| Artifact | beehiiv | cnblogs | habr | ghost |
|---|---|---|---|---|
| `register()` block in `publishing/adapters/__init__.py` | L192–199 | L136–143 | L225–230 | L184–191 |
| Adapter class import in same file | `from .beehiiv_api import BeehiivAPIAdapter` (L84) | `from .cnblogs_api import CNBlogsAPIAdapter` (L75) | `from .habr_api import HabrAPIAdapter` (L88) | `from .ghost_api import GhostAPIAdapter` |
| `*_MANIFEST` import in same file | `BEEHIIV_MANIFEST` (L31) | `CNBLOGS_MANIFEST` (L33) | `HABR_MANIFEST` (L38) | `GHOST_MANIFEST` |
| Manifest def in `publishing/_manifests.py` | L405–407 | L408–410 | L417–419 | L414–416 |
| Rationale entry in `publishing/adapters/_nofollow_rationales.py` | `"beehiiv"` (L156) | `"cnblogs"` (L176) | `"habr"` (L235) | `"ghost"` |
| Adapter module to delete | `beehiiv_api.py` | `cnblogs_api.py` | `habr_api.py` | `ghost_api.py` |
| Dedicated test module to delete | `tests/test_beehiiv_api.py` | `tests/test_cnblogs_api.py` | — | `tests/test_ghost_api.py` |
| `config/tokens.py` `all_token_revs` tuple | `("beehiiv", "beehiiv-token.json")` (L37) | — | — | `("ghost", "ghost-token.json")` |
| `config.example.toml` section | — | `[cnblogs]` block (L32–38) | — | — |
| `tests/test_phase1_cookie_adapters.py` `COOKIE_ADAPTERS` list | — | — | `("habr", "HabrAPIAdapter")` (L32) | — |

- The "add a channel" recipe (`AGENTS.md` → "Adding a new publisher adapter") is the mirror of
  this removal: one `register()` line + one manifest dict. Reverse it for each slug.
- `register()` signature lives in `publishing/registry.py`; it requires `dofollow=` and (for
  non-`True` dofollow) `rationale=`/`referral_value=`. Removing the whole `register()` block
  removes all of these together — no partial edits.

### Known false positives (do NOT touch)

- `tests/test_blogger_banner.py`, `tests/test_telegraph_banner.py`, `tests/test_ghpages_banner.py`,
  `tests/test_cli_plan_check.py` — use a local `ghost = tmp_path / "ghost.png"` / `ghost.md`
  fixture for "missing file" cases. Unrelated to the Ghost platform.
- `tests/test_bind_channel_recipes.py:56` — `TestVelogHostFilter` ("ghost" inside "HostFilter").
- `tests/test_webui_platforms_context.py:106` — comment "Wordpress ghost option removal" refers
  to a phantom WordPress UI option, not the Ghost platform.
- `src/.../adapters/cnblogs_api.py:90` — docstring example "adapter (ghost, notion, ...)"; the
  whole file is being deleted anyway.

### Institutional Learnings

- `[[feedback_grep_dofollow_map_before_shipping_adapter]]` — the dofollow data is now in the
  `register()` call + `_nofollow_rationales`, **not** a `binding_status._DOFOLLOW_BY_CHANNEL`
  map. Confirmed: `binding_status.py` does not exist in the current tree; that memory note is
  stale. No separate dofollow map to prune.
- `[[feedback_platform_retirement_known_roots_pattern]]` / `[[feedback_hidden_from_ui_pattern_for_retiring_channels]]`
  — these describe *soft* retirement (keep adapter, hide from UI, keep `_SAVE_CONFIG_KNOWN_ROOTS`).
  This plan is a *hard* removal; verify in Unit 3 that none of the four slugs are baked into
  `_SAVE_CONFIG_KNOWN_ROOTS` (grep found none — they were never round-tripped by `save_config`).
- `[[feedback_dead_code_audit_blind_spots]]` — grep misses `as`-aliases, dynamic registry, and
  `mock.patch` targets. The full pytest suite is the real tripwire; a relative-import miss only
  explodes at import time. Run the full suite, not just `py_compile`.

## Key Technical Decisions

- **Hard delete, not soft retire:** Operator explicitly wants these gone ("移除干净", no
  accounts). Keeping importable-but-unregistered adapters adds dead code with no upside.
- **Implement as one atomic commit:** Units below describe facets of a single removal. Removing
  a manifest def while its `register()` import still references it (or vice versa) leaves the
  package un-importable mid-edit. Sequence the edits, then verify once at the end. Do not land
  partial units.
- **No CLI/schema/WebUI edits:** Verified these are 100% registry-driven for platform
  enumeration. Adding edits there would be wrong and would risk breaking other channels.
- **Leave historical docs intact:** Plans/requirements/solutions are an append-only record.

## Open Questions

### Resolved During Planning

- *Are there hardcoded platform lists or counts that will break?* — No. Grep found no
  `EXPECTED_PLATFORMS`/`ALL_PLATFORMS`/count assertions. `test_manifest_contract.py` prints
  `len(registered_platforms())` dynamically (no fixed number). Parametrized gates iterate the
  live registry.
- *Does `cnblogs`/`habr`/`beehiiv` need a `tokens.py` edit?* — Only `beehiiv` and `ghost` are in
  the `all_token_revs` list (`-token.json`). `cnblogs` and `habr` use `*-credentials.json` and
  are not enumerated there.
- *Does removing slugs from `registered_platforms()` break runtime contracts?* — Desired: the
  publish CLI / schema will now reject these slugs as unknown platforms (fail-closed). Operator
  has no seeds/history referencing them.

### Deferred to Implementation

- Exact line numbers will drift if concurrent work lands first; the implementer should re-grep
  the four slugs in `src/` before editing rather than trusting the line numbers in the table.
- Whether `_manifests.py` groups the four "minimal WIP manifest" defs contiguously enough to
  remove as a block or one-by-one — resolve by reading L405–419 at edit time.

## Implementation Units

> All four units are facets of **one atomic removal commit**. Land them together; run
> verification (Unit 4) once at the end. A half-applied state leaves the package un-importable.

- [ ] **Unit 1: Unregister the four channels**

**Goal:** Remove the four `register()` calls and their now-orphaned imports from the adapter
dispatcher, so they leave `registered_platforms()`.

**Requirements:** R1, R3

**Dependencies:** None (but see atomic-commit note — pairs with Units 2–3).

**Files:**
- Modify: `src/backlink_publisher/publishing/adapters/__init__.py`

**Approach:**
- Delete the four `register("beehiiv"/"cnblogs"/"habr"/"ghost", ...)` blocks.
- Delete the four `from .{slug}_api import {Class}Adapter` import lines.
- Delete the four `{SLUG}_MANIFEST` names from the `.._manifests import (...)` block.
- Re-grep the four slugs in this file afterward → expect zero matches.

**Patterns to follow:** Mirror-reverse of the add recipe in `AGENTS.md` → "Adding a new
publisher adapter".

**Test scenarios:**
- Integration: after edit, `from backlink_publisher.publishing.adapters import *` imports
  cleanly (no `ImportError`/`NameError` from dangling references).
- Integration: `registered_platforms()` returns 24 entries, none equal to the four slugs.

**Verification:** `registered_platforms()` excludes all four; module imports without error.

- [ ] **Unit 2: Remove manifests and dofollow rationales**

**Goal:** Delete the four manifest definitions and the four dofollow-rationale entries that
only existed to support the removed `register()` calls.

**Requirements:** R3

**Dependencies:** Unit 1 (imports must already be gone, else these defs are still referenced).

**Files:**
- Modify: `src/backlink_publisher/publishing/_manifests.py` (remove `BEEHIIV_MANIFEST`,
  `CNBLOGS_MANIFEST`, `GHOST_MANIFEST`, `HABR_MANIFEST`)
- Modify: `src/backlink_publisher/publishing/adapters/_nofollow_rationales.py` (remove the
  `"beehiiv"`, `"cnblogs"`, `"ghost"`, `"habr"` keys from the `_R` dict)

**Approach:**
- Remove the four manifest dict assignments (the minimal `UiMeta`-only WIP manifests).
- Remove the four rationale entries. The dofollow gate test (`test_adapter_dofollow_gate.py`)
  parametrizes over `registered_platforms()`, so a now-unregistered slug is simply not iterated
  — no orphaned-rationale assertion exists to fail.

**Patterns to follow:** `_nofollow_rationales._R` is a plain dict keyed by slug; the manifests
are module-level dict assignments with no `__all__` to update.

**Test scenarios:**
- Edge: confirm `_R` has no key for the four slugs (a stray entry is harmless but unclean —
  R5 grep catches it).
- Test expectation: none beyond the suite-wide gates — pure deletion of data only referenced
  by the removed registrations.

**Verification:** `_manifests.py` and `_nofollow_rationales.py` contain no reference to the
four slugs; suite still green.

- [ ] **Unit 3: Remove token and config wiring**

**Goal:** Drop the credential/token plumbing for the removed channels.

**Requirements:** R3

**Dependencies:** Unit 1.

**Files:**
- Modify: `src/backlink_publisher/config/tokens.py` (remove `("beehiiv", "beehiiv-token.json")`
  and `("ghost", "ghost-token.json")` from the `all_token_revs` list)
- Modify: `config.example.toml` (remove the `[cnblogs]` comment block, L32–38)

**Approach:**
- `cnblogs` and `habr` have no `tokens.py` entry (cookie/credentials-based), so only `beehiiv`
  and `ghost` need removal there.
- The `config.example.toml` `[cnblogs]` block is the only example-config section among the four.
- Before editing, grep `_SAVE_CONFIG_KNOWN_ROOTS` for the four slugs to confirm none are present
  (expected: none — they were never round-tripped by `save_config`).

**Test scenarios:**
- Test expectation: none — `tests/test_token_revocation_midrun.py` and `tests/test_config.py`
  assert specific token behavior, not the membership of the `all_token_revs` list, so removal is
  safe and needs no test change. (Confirmed: neither asserts a fixed platform set.)

**Verification:** `all_token_revs()` no longer probes `beehiiv-token.json` / `ghost-token.json`;
`config.example.toml` has no `cnblogs` section.

- [ ] **Unit 4: Delete adapter modules + tests, then full-suite verification**

**Goal:** Delete the four adapter source modules and their dedicated tests, prune the lone
shared-test reference, and prove the whole removal is clean and green.

**Requirements:** R2, R4, R5

**Dependencies:** Units 1–3 (modules must be unreferenced before deletion).

**Files:**
- Delete: `src/backlink_publisher/publishing/adapters/beehiiv_api.py`
- Delete: `src/backlink_publisher/publishing/adapters/cnblogs_api.py`
- Delete: `src/backlink_publisher/publishing/adapters/habr_api.py`
- Delete: `src/backlink_publisher/publishing/adapters/ghost_api.py`
- Delete: `tests/test_beehiiv_api.py`
- Delete: `tests/test_cnblogs_api.py`
- Delete: `tests/test_ghost_api.py`
- Modify: `tests/test_phase1_cookie_adapters.py` (remove the `("habr", "HabrAPIAdapter")` tuple
  from `COOKIE_ADAPTERS`; the file still covers zhihu/juejin/jianshu/csdn/segmentfault/note/pikabu)

**Approach:**
- There is no dedicated `test_habr_api.py`; habr is only exercised via the parametrized
  `COOKIE_ADAPTERS` list — prune the one tuple, keep the file.
- After deletions, run the verification battery below.

**Execution note:** This unit is the verification gate for the entire change — run it last.

**Test scenarios:**
- Integration: full `pytest tests/` passes with `PYTHONHASHSEED=0` (preserves footprint gate).
- Integration: `python -m py_compile src/backlink_publisher/**/*.py` succeeds (no dangling
  imports) — but treat the full suite as the authoritative tripwire per
  `[[feedback_grep_all_legacy_import_forms_not_just_from_dotted]]`.
- Edge: `grep -rni "beehiiv\|cnblogs\|habr\|\bghost\b" src/ tests/` (excluding `__pycache__`)
  returns only the documented `ghost.png` / `HostFilter` / "ghost option" false positives — and
  zero matches for beehiiv/cnblogs/habr.
- Edge: `test_phase1_cookie_adapters.py` still passes for the remaining seven cookie adapters.

**Verification:** Full suite green; py_compile clean; `registered_platforms()` == 24; grep clean
modulo known false positives.

## System-Wide Impact

- **Interaction graph:** `registered_platforms()` is the single fan-out point. Argparse choices
  (publish CLI), `schema.validate_publish_payload`, `content_negotiation.route_tier_for`'s drift
  detector, the dofollow gate, the manifest-contract test, and the WebUI publish select all read
  it dynamically. All update automatically; none need manual edits.
- **Error propagation:** Post-removal, a publish request naming one of the four slugs is rejected
  fail-closed — `schema.validate_publish_payload` raises before dispatch, and `route_tier_for`
  applies `_DEFAULT_TIER="c"` (reject `content_html`-only) for unknown platforms. This is the
  intended behavior.
- **State lifecycle risks:** None in code. On-disk credential files (if any) are orphaned but
  harmless; noted as an operator cleanup step, not a code concern.
- **API surface parity:** The publish CLI `--platform` accepted-value set shrinks by four. No
  other interface enumerates platforms statically.
- **Unchanged invariants:** The 24 remaining channels, the registry/manifest/rationale
  contracts, the dofollow gate (`dofollow=` + `rationale>=80ch` + `referral_value`), and the
  add-a-channel recipe are all unchanged — this plan only deletes four registrations and their
  exclusive supporting artifacts.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| A relative-import or `mock.patch` string reference to a deleted module slips past grep and only fails at import time | Run the **full** pytest suite (not just `py_compile`) — per `[[feedback_grep_all_legacy_import_forms_not_just_from_dotted]]` it is the only reliable tripwire. |
| Partial application leaves the package un-importable (e.g., manifest removed but import remains) | Treat all units as one atomic commit; verify once at the end; never land a half-state. |
| Line numbers drift if concurrent worktree work lands first (repo runs many parallel `bp-*/` branches) | Implementer re-greps the four slugs in `src/` before editing instead of trusting the table's line numbers; re-verify `HEAD`/branch per `[[feedback_ce_work_must_reverify_state]]`. |
| A "ghost.png" / "HostFilter" false positive gets deleted by an over-eager find-replace | Removal must be word-boundary / slug-aware; the false-positive list above is explicit. |
| `monolith_budget.toml` ceiling for `adapters/__init__.py` | Removing lines only lowers SLOC; ceilings are maxima, so no budget bump needed. |

## Documentation / Operational Notes

- Optional operator step (not code): delete any stale `~/.config/backlink-publisher/beehiiv-token.json`,
  `ghost-token.json`, `cnblogs-credentials.json`, `habr-credentials.json` if they exist.
- No README/AGENTS/CHANGELOG channel list to update (verified zero references).
- Consider a one-line CHANGELOG entry at ship time noting the four channels were removed
  (no account / unusable), bringing supported platforms 28 → 24.

## Sources & References

- Registry/dispatcher: `src/backlink_publisher/publishing/adapters/__init__.py`
- Manifests: `src/backlink_publisher/publishing/_manifests.py`
- Dofollow rationales: `src/backlink_publisher/publishing/adapters/_nofollow_rationales.py`
- Token wiring: `src/backlink_publisher/config/tokens.py`
- Registry-driven enumeration contract: `AGENTS.md` → "Adding a new publisher adapter";
  `tests/test_r9_extension_readiness.py`, `tests/test_manifest_contract.py`,
  `tests/test_adapter_dofollow_gate.py`
- Related memory: `[[feedback_grep_dofollow_map_before_shipping_adapter]]`,
  `[[feedback_hidden_from_ui_pattern_for_retiring_channels]]`,
  `[[feedback_grep_all_legacy_import_forms_not_just_from_dotted]]`
