"""Transient-error fallback classification (Plan 2026-06-15-001, Unit A2).

GROUNDWORK ONLY — this module decides *whether* a transient publish failure is
safe to fall back to the next same-platform adapter. It is intentionally NOT yet
wired into ``_registry_dispatch.dispatch()``: an addressable-set investigation
(plan §Open Questions, resolved 2026-06-15) found ZERO adapter transitions that
qualify today, so the dispatch fallback arm is deferred. The classifier, the two
empty evidence-gated whitelists, and the provenance marker land now so the lever
can be switched on later with a single whitelist entry once evidence exists.

Safety model (preserves R2 — never create a duplicate live link):

1. A transient is fallback-safe ONLY when the raising adapter positively asserts
   that its 429 was a *pre-create rejection* (stamped via :func:`mark_pre_create_429`
   at the create-POST site). A bare/unidentified ``ExternalServiceError`` — whose
   status the dispatcher cannot positively read — defaults to FAIL_FAST. We do NOT
   reuse ``retry.classify_exception``'s ``ExternalServiceError -> TRANSIENT`` mapping;
   that is the inverse of what duplicate-safety needs.
2. 5xx is ambiguous (the post may already exist) -> FAIL_FAST unless the platform
   is on :data:`IDEMPOTENCY_SAFE_5XX` (ships empty).
3. Falling to a *different publish mechanism on the same account* (e.g. an API
   adapter -> a browser adapter for the same platform) is materially riskier than
   falling between two same-mechanism adapters and is held to a separate gate:
   :data:`CROSS_MECHANISM_FALLBACK` (ships empty). Default fail-fast on both.
4. ``AntiBotChallengeError`` (a subclass of ``ExternalServiceError``) and network
   errors are never fallback-safe — checked most-derived-type first.
"""

from __future__ import annotations

from enum import Enum

from backlink_publisher._util.errors import (
    AntiBotChallengeError,
    ExternalServiceError,
)

from ..adapters.retry import ErrorClass, classify_exception

# Marker attribute stamped on an exception by the raising adapter to assert that
# its 429 was returned by the server BEFORE the post was created (the only state
# in which a cross-adapter fallback cannot duplicate). Private attribute name so
# it never collides with exception ``args``/``message``.
_PRE_CREATE_429_ATTR = "_blp_pre_create_429"

# --- Evidence-gated whitelists. BOTH ship EMPTY. ---------------------------------
# A platform/transition is added ONLY after confirming the error cannot leave a
# partially-created post (plan §Key Technical Decisions). Default fail-fast.

#: Platforms whose 5xx on a create POST is proven idempotency-safe to fall back on.
IDEMPOTENCY_SAFE_5XX: frozenset[str] = frozenset()

#: Approved cross-mechanism fallback transitions, as ``(from_adapter, to_adapter)``
#: class-name pairs on the same account. Default-empty; each entry is evidence-gated.
#:
#: ``MediumAPIAdapter -> MediumBraveAdapter`` (A1 unlock 2026-06-15): the API
#: adapter stamps pre-create-429 provenance (see ``mark_pre_create_429`` in
#: ``medium_api``) — a 429 on the create POST means Medium rejected the request
#: BEFORE creating the post, so falling to Brave creates the first and ONLY post,
#: not a duplicate. The riskier ``Brave -> Browser`` transition stays blocked
#: because Brave does NOT stamp provenance, so ``classify_transient`` returns
#: FAIL_FAST for it (a Brave failure can leave a draft → Browser would duplicate).
CROSS_MECHANISM_FALLBACK: frozenset[tuple[str, str]] = frozenset(
    {("MediumAPIAdapter", "MediumBraveAdapter")}
)


class TransientDecision(str, Enum):
    """Outcome of :func:`classify_transient`."""

    FALLBACK_SAFE = "fallback_safe"
    FAIL_FAST = "fail_fast"


def mark_pre_create_429(exc: BaseException) -> None:
    """Stamp ``exc`` as a pre-create 429 rejection (safe to fall back on).

    Called by an adapter at the create-POST site when it converts a retry-exhausted
    429 into an ``ExternalServiceError`` — the only point with the provenance to
    know the post was not created. No-op-safe on any exception object.
    """
    setattr(exc, _PRE_CREATE_429_ATTR, True)


def has_pre_create_429(exc: BaseException) -> bool:
    """Return True if ``exc`` was stamped by :func:`mark_pre_create_429`."""
    return getattr(exc, _PRE_CREATE_429_ATTR, False) is True


def classify_transient(
    exc: BaseException,
    *,
    platform: str,
    transition: tuple[str, str],
    same_mechanism: bool,
) -> TransientDecision:
    """Decide whether ``exc`` may degrade to the next same-platform adapter.

    Args:
        exc: the exception raised by the failing adapter.
        platform: the platform key (for the 5xx whitelist lookup).
        transition: ``(from_adapter_class_name, to_adapter_class_name)`` — the
            candidate fallback edge, for the cross-mechanism whitelist lookup.
        same_mechanism: whether ``from`` and ``to`` publish via the same mechanism
            (both API, or both browser). Computed by the caller from adapter metadata.

    Returns FALLBACK_SAFE only when duplicate-publish safety is positively
    established; every uncertain case is FAIL_FAST.
    """
    # 1. Most-derived first: anti-bot challenge IS-A ExternalServiceError but is
    #    never a transient we route around.
    if isinstance(exc, AntiBotChallengeError):
        return TransientDecision.FAIL_FAST

    # 2. Only ExternalServiceError is even a candidate. Network errors,
    #    DependencyError, and anything else fail fast.
    if not isinstance(exc, ExternalServiceError):
        return TransientDecision.FAIL_FAST

    # 3. Mechanism gate. Same-mechanism is allowed; cross-mechanism only if the
    #    specific transition is whitelisted (empty by default).
    if not same_mechanism and transition not in CROSS_MECHANISM_FALLBACK:
        return TransientDecision.FAIL_FAST

    # 4. 5xx is post-create-ambiguous -> only safe on a whitelisted platform.
    if classify_exception(exc) is ErrorClass.HTTP_5XX:
        if platform in IDEMPOTENCY_SAFE_5XX:
            return TransientDecision.FALLBACK_SAFE
        return TransientDecision.FAIL_FAST

    # 5. A 429 is safe to fall back on ONLY with positive pre-create provenance.
    #    A bare/unidentified ExternalServiceError has no such proof -> fail fast.
    if has_pre_create_429(exc):
        return TransientDecision.FALLBACK_SAFE

    return TransientDecision.FAIL_FAST
