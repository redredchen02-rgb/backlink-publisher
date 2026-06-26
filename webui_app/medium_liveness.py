"""Medium liveness probe — re-export shim (Plan 2026-06-01-001 U7).

Orchestration logic moved to webui_app.services.medium_liveness_service.
Adapter probe lives at backlink_publisher.publishing.adapters.medium_liveness.
"""
from __future__ import annotations

# Re-export adapter symbols unchanged.
from backlink_publisher.publishing.adapters.medium_liveness import (
    _active_probe,
    _load_storage_state_for_probe,
    _storage_state_path,
    LivenessResult,
    MEDIUM_LIVENESS_ACTIVE_PROBE_ENABLED,
)

# Re-export service symbols (keeps existing call sites and tests working).
from .services.medium_liveness_service import (
    _last_verified_age_seconds,
    medium_liveness_check,
)

__all__ = [
    "LivenessResult",
    "MEDIUM_LIVENESS_ACTIVE_PROBE_ENABLED",
    "_active_probe",
    "_load_storage_state_for_probe",
    "_storage_state_path",
    "_last_verified_age_seconds",
    "medium_liveness_check",
]
