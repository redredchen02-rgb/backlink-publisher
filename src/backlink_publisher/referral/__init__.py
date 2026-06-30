"""Channel-level referral attribution (Plan 2026-06-15-004).

Pure-read attribution: reuse the existing ``click_track`` GA4 path to pull
referral sessions, map each GA4 ``sessionSource`` to a backlink channel, and
record per-channel ``referral.observed`` events for the scorecard and g3 gate.
Nothing in the publish pipeline changes, so the dofollow backlink is preserved.
"""

from __future__ import annotations

__all__: list[str] = []
