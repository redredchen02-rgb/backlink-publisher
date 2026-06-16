"""Pipeline route façade — Wave 3 Unit 5 (2026-06-11).

Exports ``bp`` (the plan/generate/validate side) and ``bp_publish`` (the
publish side) so ``routes/__init__.py`` can register both.

Kept for backward compatibility: code that does ``from .pipeline import bp``
still gets the plan-side blueprint.  External callers that patch
``webui_app.routes.pipeline.*`` must be updated to patch the concrete
sub-module (``pipeline_plan`` or ``pipeline_publish``) after this split.
"""
from __future__ import annotations

from .pipeline_plan import bp  # noqa: F401 — legacy export, plan-side blueprint
from .pipeline_publish import bp as bp_publish  # noqa: F401
