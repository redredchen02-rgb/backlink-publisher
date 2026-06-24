"""backlink-publisher root package.

Canonical import paths:

  - ``backlink_publisher.anchor.*``  (lang, metrics, profile, resolver, scheduler, preflight)
  - ``backlink_publisher.content.*``  (fetch, scraper, themed_gen)
  - ``backlink_publisher.linkcheck.*``  (http, language, verify)
  - ``backlink_publisher._util.*``  (errors, io, jsonl, logger, markdown, url, …)
  - ``backlink_publisher.publishing.adapters.*``  (blogger, medium, telegraph, …)

See AGENTS.md §Import Conventions for the full table.

Public facade (plan 2026-06-22-001 U6) — ``import backlink_publisher`` is meaningful::

    import backlink_publisher as bp
    plans  = bp.plan(seeds)            # in-process plan-backlinks  -> PipeResult
    valid  = bp.validate(plans.rows)   # in-process validate        -> PipeResult
    result = bp.publish(valid.rows)    # in-process (API-tier)      -> PipeResult
    bp.dispatch(payload, "draft", cfg) # low-level single-payload   -> AdapterResult
    try:
        ...
    except bp.ExternalServiceError as exc:
        back_off(exc.exit_code)        # every error class carries .exit_code

The error taxonomy imports eagerly (``_util.errors`` is a leaf). The pipeline
entry points are LAZY via module ``__getattr__`` (PEP 562) so ``import
backlink_publisher`` stays cheap and never eagerly pulls the adapter graph (which
would revive a known import cycle and force adapter registration as a side
effect of merely importing the package).
"""
from __future__ import annotations

from typing import Any

from ._util.errors import (
    AntiBotChallengeError,
    AuthExpiredError,
    BannerUploadError,
    ContentRejectedError,
    DependencyError,
    ExternalServiceError,
    InputValidationError,
    InternalError,
    PipelineError,
    RegistryError,
    UsageError,
)

__all__ = [
    # ── typed error taxonomy (eager; each carries ``.exit_code``) ──
    "PipelineError",
    "UsageError",
    "InputValidationError",
    "DependencyError",
    "ExternalServiceError",
    "AntiBotChallengeError",
    "RegistryError",
    "AuthExpiredError",
    "BannerUploadError",
    "ContentRejectedError",
    "InternalError",
    # ── pipeline entry points (lazy — resolved by __getattr__) ──
    "plan",
    "validate",
    "publish",
    "dispatch",
    "register_all_adapters",
    "registered_platforms",
]


def __getattr__(name: str) -> Any:  # PEP 562 — lazy facade resolution
    if name in ("plan", "validate", "publish"):
        from . import sdk

        return getattr(sdk, name)
    if name == "dispatch":
        # Low-level, single already-constructed payload → AdapterResult. The high-
        # level batch entry is ``publish`` (plan→validate→publish over rows).
        from .publishing.adapters import publish as _dispatch

        return _dispatch
    if name == "register_all_adapters":
        from .publishing.adapters import register_all_adapters

        return register_all_adapters
    if name == "registered_platforms":
        from .publishing.registry import registered_platforms

        return registered_platforms
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
