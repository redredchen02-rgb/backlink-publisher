# Runbook: seal & release v0.6.0

> **Status: STAGED — trigger held.** Everything below is prepared; do NOT fire
> until the precondition passes. The version line in `pyproject.toml` is
> deliberately still `0.5.0` on the `feat/v060-finish-line` branch so that
> merging this branch first does not stamp a half-migrated `0.6.0` onto `main`.

There is **no automated release-seal CLI** — `phase0-seal` is the Telegraph
money-page ship-gate, unrelated to version releases. Releasing is this manual
checklist (precedent: the completed `docs/plans/2026-06-23-002-release-v0.5.0-prep-plan.md`).

## Precondition (the held trigger)

Fire only once **both** fleet SPA branches have merged to `main`, so 0.6.0 is a
coherent milestone rather than a half-strangled migration:

- [ ] `feat/webui-phase-a` merged (broad DataTable/StatusBadge rollout — U5).
- [ ] `fix/webui-uiux-stabilization` merged (TopBar/a11y/Ctrl+K region — U8).
- [ ] `git fetch && git log origin/main` shows those merges; re-run the full
      unit gate green at that HEAD.

If the operator chooses to cut 0.6.0 *without* those (accepting an incomplete
SPA migration in the release), that is a valid alternative — just move the
remaining SPA units to the `0.6.1` line in the roadmap and CHANGELOG first.

## Fire checklist

1. **Bump the version (2 lines, both in `pyproject.toml`):**
   - [ ] `version = "0.5.0"` → `version = "0.6.0"` (line ~7, the canonical source;
         `app_version()` reads it via `importlib.metadata`).
   - [ ] `[tool.towncrier] version = "0.5.0"` → `"0.6.0"` (line ~276; towncrier is
         vestigial — `changelog.d/` holds only `.gitkeep` — but keep it consistent).
   - [ ] **Do NOT** touch `frontend/package.json` (`version: "0.0.0"` is a
         deliberately-unversioned private SPA).

2. **Reinstall editable so the running app/tests observe 0.6.0:**
   - [ ] `.venv\Scripts\python.exe -m pip install -e ".[dev]"` (pip shebang is
         broken — always `python -m pip`).

3. **Regenerate the OpenAPI spec (generated artifact, not hand-edited):**
   - [ ] `set PYTHONPATH=src && python scripts/gen_openapi.py` → updates
         `openapi/backlink-api.yaml` `version: 0.6.0`.
   - [ ] Verify `python scripts/gen_openapi.py --check` passes (this is the
         `api-contract.yml` drift gate; an `info.version` change is not an
         oasdiff breaking change).

4. **Promote the CHANGELOG:**
   - [ ] Rename `## [Unreleased]` → `## [0.6.0] - <YYYY-MM-DD>` (keep the F1/F2/F3
         `### Added` entries already staged there, plus the R12 fixes).
   - [ ] Add a fresh empty `## [Unreleased]` above it.
   - [ ] Fix the bottom compare links: change
         `[Unreleased]: …/compare/v0.5.0...HEAD` →
         `[Unreleased]: …/compare/v0.6.0...HEAD`, and add
         `[0.6.0]: …/releases/tag/v0.6.0`.

5. **Run all gates green (at the release commit):**
   - [ ] `PYTHONPATH=src pytest tests/` (incl. `test_no_monolith_regrowth`,
         `test_no_complexity_regrowth`, the console-script entrypoint tests).
   - [ ] `python -m ruff check src/ webui_app/ webui_store/`
   - [ ] `python -m mypy src/backlink_publisher` (full-package invocation — the
         single-file `_MAX_ENTRIES` `has-type` note is a single-file-check quirk,
         not a real error).
   - [ ] `make reconcile-check`
   - [ ] Confirm the GitHub Actions `unit` matrix (3.11 / 3.12) is green at the
         release commit — `main` has advanced well past the last-verified
         `7b6441a7`; do not assume, re-check.

6. **Tag (release publication is operator-timed):**
   - [ ] `git tag v0.6.0` at the release commit (delete + re-push if a
         placeholder tag exists, per the 2026-06-23-002 precedent).
   - [ ] GitHub Release publication is deliberately operator-timed — tag first,
         publish when ready.

## Version-bump surface (every hard-coded `0.5.0`)

| File | Current | Action |
|---|---|---|
| `pyproject.toml` (~L7) | `version = "0.5.0"` | → `"0.6.0"` (canonical) |
| `pyproject.toml` (~L276) | towncrier `version = "0.5.0"` | → `"0.6.0"` |
| `openapi/backlink-api.yaml` (~L6) | `version: 0.5.0` | regenerate via `gen_openapi.py` |
| `CHANGELOG.md` | `[Unreleased]` + compare links | promote + relink |
| `frontend/package.json` | `version: "0.0.0"` | **leave unchanged** |
| runtime | `app_version()` | no file edit — needs the editable reinstall |

Prose "Since v0.5.0…" references in `ARCHITECTURE.md` / `CLAUDE.md` / `docs/` are
historical, not version declarations — leave them.
