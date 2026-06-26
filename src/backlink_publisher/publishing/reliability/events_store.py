"""Event-store helper for ``reliability.decision`` events (Plan 2026-06-15-006, Unit 2).

Persists the policy-layer decision into events.db so observe-mode signals are
queryable — ``emit_attempt`` only logs to stderr, which ``scorecard.success_rate``
explicitly rejects as a source. Written directly via ``EventStore.append`` (the
``referral.store`` direct-append pattern), NOT through the projector.

The ``EventStore`` floor check (``kinds.REQUIRED_FIELDS``) is presence-only — it
does not validate the *value* of ``decision``. A typo'd decision would otherwise
write a valid-looking row that pollutes readiness (Unit 4) and the alert path
(Unit 6). So this helper validates ``decision`` against the closed vocabulary and
quarantines an unknown value rather than persisting it.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Final

from backlink_publisher.events.kinds import RELIABILITY_DECISION
from backlink_publisher.events.store import EventStore

#: The closed vocabulary of policy-layer decisions. Four map 1:1 to the
#: ``publish_with_policy`` observe/enforce branches; ``circuit_state_unreadable``
#: is the Unit 8 corrupt-state sentinel; ``degraded`` is the Unit 6 alert signal.
DECISIONS: Final[frozenset[str]] = frozenset(
    {
        "would_skip_policy",
        "would_skip_circuit",
        "skipped_policy",
        "skipped_circuit_open",
        "degraded",
        "circuit_state_unreadable",
    }
)


def append_reliability_decision(
    store: EventStore,
    *,
    platform: str,
    decision: str,
    mode: str,
    reason: str | None = None,
) -> int:
    """Record a ``reliability.decision`` event for one policy-layer decision.

    Returns the new event id, or ``-1`` if the decision value is not in
    :data:`DECISIONS` (quarantined for triage) or the payload was quarantined by
    the store's floor check.
    """
    if decision not in DECISIONS:
        store.quarantine(
            reason=f"unknown reliability decision: {decision!r}",
            failure_type="unknown_decision",
            source=RELIABILITY_DECISION,
            record_identity=platform,
            raw_payload={"platform": platform, "decision": decision, "mode": mode},
        )
        return -1
    return store.append(
        RELIABILITY_DECISION,
        {
            "platform": platform,
            "decision": decision,
            "mode": mode,
            "reason": reason,
            "ts": datetime.now(UTC).isoformat(),
        },
    )
