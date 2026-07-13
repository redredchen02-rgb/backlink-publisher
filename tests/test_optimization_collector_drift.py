"""_extract_platform_drift must read the real canary-health schema (audit [09]).

collector._extract_platform_drift derived drift as `1 if entry.get("forward_path_drift")`,
but canary/store.py (the sole writer of canary-health.json) never writes that key —
its evergreen records carry `status` ("drift-confirmed" etc.) and `quarantined`.
So drift_count was always 0 and Rule 1 (_rule_canary_drift, fires at >=max_strikes)
could never trip from real data. It also iterated the `_publish_path` sentinel key
as if it were a platform, injecting a bogus platform into the merged stats.
"""
from __future__ import annotations

__tier__ = "unit"

from backlink_publisher.optimization.collector import _extract_platform_drift


def test_drift_derived_from_status_and_quarantined_not_missing_key():
    canary_data = {
        "medium": {"status": "drift-confirmed", "quarantined": False},
        "blogger": {"status": "link-alive", "quarantined": True},
        "devto": {"status": "link-alive", "quarantined": False},
        # forward-path sentinel — a nested structure, NOT a platform record
        "_publish_path": {"medium": {"status": "link-alive", "degraded": True}},
    }

    platforms = _extract_platform_drift(canary_data)["platforms"]

    assert platforms["medium"]["drift_count"] == 1   # drift-confirmed
    assert platforms["blogger"]["drift_count"] == 1  # quarantined
    assert platforms["devto"]["drift_count"] == 0    # healthy
    assert "_publish_path" not in platforms          # sentinel must be skipped
