"""Work-themed generation run registry and output parsing — Plan 2026-06-01-001 U6.

Flask-free: no request/session access. Owns the in-memory run registry
extracted from helpers/cli_runner.py and the plan-output parser extracted
from routes/sites.py.
"""
from __future__ import annotations

import json

# In-memory run registry — maps run_id → {main_url, summary, rows}.
# Evicted FIFO when the cap is exceeded.  Lives here (not in cli_runner) so
# sites.py can be imported without pulling all the subprocess/io helpers.
_RUNS: dict[str, dict] = {}
_MAX_RUNS: int = 50


def register_run(run_id: str, main_url: str, summary: dict, rows: list[dict]) -> None:
    """Add a completed plan run to the registry, evicting oldest if at cap."""
    _RUNS[run_id] = {"main_url": main_url, "summary": summary, "rows": rows}
    if len(_RUNS) > _MAX_RUNS:
        oldest = sorted(_RUNS.keys())[:-_MAX_RUNS]
        for k in oldest:
            _RUNS.pop(k, None)


def get_run(run_id: str) -> dict | None:
    """Return the run record for *run_id*, or None if not found."""
    return _RUNS.get(run_id)


def parse_lines(raw: str) -> list[str]:
    """Split a multi-line text input into non-empty stripped lines."""
    if not raw:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def parse_plan_output(stdout: str, entry) -> list[dict]:
    """Parse plan-backlinks JSONL stdout into per-work-URL success rows.

    *entry* must expose ``entry.main_url`` (ThreeUrlConfig or similar).
    Deduplicates canonical URLs — first occurrence wins.
    """
    rows: list[dict] = []
    seen: set[str] = set()
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        canonical = (
            payload.get("seo", {}).get("canonical_url")
            or payload.get("url") or ""
        )
        if canonical and canonical not in seen:
            seen.add(canonical)
            rows.append({"work_url": canonical, "status": "success"})
    return rows
