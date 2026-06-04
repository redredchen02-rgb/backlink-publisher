---
name: System Optimization — test tier lessons
description: Lessons from implementing test tier markers, CI split, and coverage baseline
type: feedback
updated: 2026-06-04
expires: never
platform: universal
---

# System Optimization Lessons

## Test Tier Markers
- `__tier__` must be placed after `from __future__` imports (Python syntax requirement), not before
- Custom markers should be registered in `pyproject.toml` (via `[tool.pytest.ini_options].markers`), not in `conftest.py`, to avoid `UnknownMarkWarning`
- `--strict-markers` should be passed via CLI, not `addopts`, because conftest loads before addopts take effect

## CI Split
- GitHub Actions: unit every push, integration/e2e PR only
- xdist for unit/integration, single-core for e2e

## Coverage Baseline
- Only unit tier for coverage baseline (integration/e2e have too many environmental variables)
- Use `pytest-cov>=6.0`, `--cov --cov-branch --cov-report=json`

## GitLab Setup
- Two remotes: `origin` (GitHub, auth expired) and `gitlab` (GitLab, working)
- Use `glab` CLI for GitLab operations (MR create, merge, etc.)
- For git push, use PAT token in URL: `https://username:token@gitlab.com/org/repo.git`
