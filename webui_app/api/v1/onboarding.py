"""Onboarding endpoints (Plan 2026-07-09-001).

GET  /api/v1/onboarding/status — read-only aggregate; origin-guarded at GET time
     (same allowlist as /app-config) so a DNS-rebinding page cannot read the
     operator's dismissed flag.
POST /api/v1/onboarding/dismiss  — persist 'dismissed'; covered by the app-wide
     CSRF before_request guard (POST/PUT/PATCH/DELETE).
POST /api/v1/onboarding/reset    — clear 'dismissed' (tests / demos); CSRF-guarded.
"""

from __future__ import annotations

from typing import Any

from flask import current_app, jsonify

from ...helpers.security import _check_bind_origin_or_abort
from ..onboarding_api import OnboardingAPI
from . import bp


def _guard_sensitive_get() -> None:
    """GET-time Origin/Referer check, gated by ORIGIN_GUARD_ENABLED (off under pytest)."""
    if current_app.config.get("ORIGIN_GUARD_ENABLED", True):
        _check_bind_origin_or_abort()


@bp.get("/onboarding/status")
def onboarding_status() -> Any:
    _guard_sensitive_get()
    return jsonify(OnboardingAPI().status())


@bp.post("/onboarding/dismiss")
def onboarding_dismiss() -> Any:
    OnboardingAPI().dismiss()
    return jsonify({"ok": True})


@bp.post("/onboarding/reset")
def onboarding_reset() -> Any:
    OnboardingAPI().reset()
    return jsonify({"ok": True})
