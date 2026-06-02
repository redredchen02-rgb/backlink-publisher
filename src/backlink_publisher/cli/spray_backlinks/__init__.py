"""``spray-backlinks`` — operator-invoked multi-platform fan-out drafting verb.

Takes ONE seed row and fans it out into N publish-ready rows (one per selected
platform), each LLM-rewritten for body distinctness and anchor-resolved, gated
by a smart filter + hard blast-radius cap, sanity-checked against a link/anchor
diversity audit, and (optionally) dispatched in a jittered burst.

This is a *drafting* verb: it emits a human-reviewable JSONL artifact that flows
into ``validate-backlinks`` / ``publish-backlinks``. The LLM rewrite is confined
to this verb (single auditable boundary); the publish path stays LLM-free. See
``docs/plans/2026-06-02-005-feat-spray-backlinks-fanout-plan.md``.
"""

from .core import main

__all__ = ["main"]
