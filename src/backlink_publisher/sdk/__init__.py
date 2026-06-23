"""Embeddable SDK — in-process pipeline entry points (plan 2026-06-22-001 U5/U6).

    from backlink_publisher.sdk import plan, validate, publish, PipelineAPI, PipeResult

The thin ``plan`` / ``validate`` / ``publish`` functions accept Python rows
(a ``list[dict]``, a single ``dict``, or an already-serialized JSONL string) and
return a structured :class:`PipeResult`. They wrap the relocated
:class:`PipelineAPI`:

  - ``plan(seed)``     → ``PipelineAPI().plan``        (in-process plan-backlinks)
  - ``validate(rows)`` → ``PipelineAPI().validate``    (in-process validate-backlinks)
  - ``publish(rows)``  → ``PipelineAPI().publish_seed`` (rows are self-describing —
    platform/mode live in each row; in-process for API-tier, CLI subprocess for
    browser-tier, see :mod:`._publish_runtime`)
"""

from __future__ import annotations

import json
from typing import Any

from .api import PipelineAPI, PipeResult

__all__ = ["plan", "validate", "publish", "PipelineAPI", "PipeResult"]


def _to_jsonl(rows: Any) -> str:
    """Coerce input to a JSONL string: pass a string through, serialize a dict as
    one line, or join a sequence of dicts one-per-line."""
    if isinstance(rows, str):
        return rows
    if isinstance(rows, dict):
        return json.dumps(rows)
    return "\n".join(json.dumps(r) for r in rows)


def plan(seed: Any, *, work_count: int | None = None) -> PipeResult:
    """Generate backlink plans from seed rows (in-process plan-backlinks)."""
    return PipelineAPI().plan(_to_jsonl(seed), work_count=work_count)


def validate(rows: Any, *, no_check_urls: bool = True) -> PipeResult:
    """Validate planned-backlink rows (in-process validate-backlinks)."""
    return PipelineAPI().validate(_to_jsonl(rows), no_check_urls=no_check_urls)


def publish(rows: Any) -> PipeResult:
    """Publish self-describing rows (platform/mode carried in each row)."""
    return PipelineAPI().publish_seed(_to_jsonl(rows))
