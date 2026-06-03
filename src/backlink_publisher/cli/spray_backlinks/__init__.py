"""``spray-backlinks`` — operator-invoked multi-platform fan-out drafting verb.

Takes one or more seed rows (multi-seed) and fans each out into N publish-ready
rows (one per selected platform), each LLM-rewritten for body distinctness and
anchor-resolved, gated by a smart filter + hard blast-radius cap, sanity-checked
against a link/anchor diversity audit, and (optionally) dispatched in a jittered
burst. Per-seed failure does not abort the run; output rows carry a ``seed_id``
field. Cross-seed governance (U4): within a run each (main_domain, platform)
pair is only used once; subsequent seeds targeting the same domain automatically
skip that platform. Resume (U5): ``--resume`` skips completed seeds and retries
failures via checkpoint files.

This is a *drafting* verb: it emits a human-reviewable JSONL artifact that flows
into ``validate-backlinks`` / ``publish-backlinks``. The LLM rewrite is confined
to this verb (single auditable boundary); the publish path stays LLM-free. See
``docs/plans/2026-06-02-005-feat-spray-backlinks-fanout-plan.md``.
"""

from .core import main

__all__ = ["main"]
