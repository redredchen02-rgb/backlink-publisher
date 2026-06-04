---
name: backlink-publisher
description: Backlink publishing pipeline (20+ platforms)
type: project
updated: 2026-06-04
expires: 2026-07-04
platform: universal
---

# backlink-publisher

## Current Status
- **Branch**: main (up-to-date with gitlab/main)
- **Latest**: Phases 1-3 — Pydantic v2 typed model validation in pipeline dispatch
- **Remote**: gitlab.com/redredchen01/backlink-publisher (primary, SSH)
- **CI**: GitHub Actions (`.github/workflows/ci.yml`) — GitLab has no `.gitlab-ci.yml`

## Completed This Session (Phases 1-3, 2026-06-04)
- **Phase 1**: Pydantic v2 typed payload models (5 models + factory helpers) in `_payload_types.py` — 42 unit tests
- **Phase 2**: `validate_and_convert_input()` / `validate_and_convert_output()` with lazy imports — 5 tests
- **Phase 3**: Pipeline dispatch uses typed model validation at all 3 stage boundaries (plan→validate→publish) — 6 integration tests
- **Zero regression**: 53 Phase tests pass; full suite 9598/19 passed/failed (all pre-existing)
- **GitLab push**: SSH key added to GitLab account, upstream set to gitlab/main

## Notes
- egg-info files are dirty from pip installs — not real changes
- `.omo/` directory is auto-generated and untracked
- GitHub account `redredchen01` is **suspended** — cannot push to origin; GitLab is the only working remote
- SSH is now working for GitLab (key added to `gitlab.com`)
