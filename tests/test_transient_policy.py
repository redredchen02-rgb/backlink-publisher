"""Unit tests for the transient-fallback classifier (Plan 2026-06-15-001, Unit A2).

Verifies the duplicate-publish safety model: FALLBACK_SAFE requires positive
pre-create provenance AND a whitelisted/same-mechanism transition; everything
uncertain fails fast; both whitelists ship empty.
"""

__tier__ = "unit"

from backlink_publisher._util.errors import (
    AntiBotChallengeError,
    DependencyError,
    ExternalServiceError,
)
from backlink_publisher.publishing.reliability import transient_policy as tp
from backlink_publisher.publishing.reliability.transient_policy import (
    TransientDecision,
    classify_transient,
    has_pre_create_429,
    mark_pre_create_429,
)

# A same-mechanism transition (e.g. API -> API) used by the happy-path cases.
_SAME = ("PrimaryAPIAdapter", "SecondaryAPIAdapter")


def _pre_create_429() -> ExternalServiceError:
    exc = ExternalServiceError("medium api rate-limited (429)")
    mark_pre_create_429(exc)
    return exc


def test_whitelists_ship_empty():
    """Both evidence-gated whitelists start empty (default fail-fast)."""
    assert tp.IDEMPOTENCY_SAFE_5XX == frozenset()
    assert tp.CROSS_MECHANISM_FALLBACK == frozenset()


def test_provenance_marker_roundtrip():
    exc = ExternalServiceError("429")
    assert has_pre_create_429(exc) is False
    mark_pre_create_429(exc)
    assert has_pre_create_429(exc) is True


def test_pre_create_429_same_mechanism_is_fallback_safe():
    """Happy path: adapter-asserted pre-create 429, same mechanism -> FALLBACK_SAFE."""
    decision = classify_transient(
        _pre_create_429(), platform="medium", transition=_SAME, same_mechanism=True
    )
    assert decision is TransientDecision.FALLBACK_SAFE


def test_bare_external_service_error_fails_fast():
    """Unidentified ExternalServiceError (no provenance) -> FAIL_FAST.

    Explicitly diverges from retry.classify_exception which maps bare
    ExternalServiceError -> TRANSIENT.
    """
    exc = ExternalServiceError("Medium /me returned HTTP 500")
    decision = classify_transient(
        exc, platform="medium", transition=_SAME, same_mechanism=True
    )
    assert decision is TransientDecision.FAIL_FAST


def test_5xx_fails_fast_when_platform_not_whitelisted():
    exc = ExternalServiceError("service returned HTTP 503")
    mark_pre_create_429(exc)  # even a (wrongly) stamped 5xx must fail fast
    decision = classify_transient(
        exc, platform="velog", transition=_SAME, same_mechanism=True
    )
    assert decision is TransientDecision.FAIL_FAST


def test_5xx_fallback_safe_when_platform_whitelisted(monkeypatch):
    monkeypatch.setattr(tp, "IDEMPOTENCY_SAFE_5XX", frozenset({"velog"}))
    exc = ExternalServiceError("service returned HTTP 503")
    decision = classify_transient(
        exc, platform="velog", transition=_SAME, same_mechanism=True
    )
    assert decision is TransientDecision.FALLBACK_SAFE


def test_cross_mechanism_blocked_until_whitelisted():
    """A pre-create 429 across mechanisms (API -> browser) is blocked by default."""
    cross = ("MediumAPIAdapter", "MediumBraveAdapter")
    decision = classify_transient(
        _pre_create_429(), platform="medium", transition=cross, same_mechanism=False
    )
    assert decision is TransientDecision.FAIL_FAST


def test_cross_mechanism_allowed_when_transition_whitelisted(monkeypatch):
    cross = ("MediumAPIAdapter", "MediumBraveAdapter")
    monkeypatch.setattr(tp, "CROSS_MECHANISM_FALLBACK", frozenset({cross}))
    decision = classify_transient(
        _pre_create_429(), platform="medium", transition=cross, same_mechanism=False
    )
    assert decision is TransientDecision.FALLBACK_SAFE


def test_anti_bot_challenge_fails_fast():
    """AntiBotChallengeError IS-A ExternalServiceError but must fail fast (ordering)."""
    exc = AntiBotChallengeError("challenge wall")
    mark_pre_create_429(exc)  # even if mis-stamped, the type check wins
    decision = classify_transient(
        exc, platform="medium", transition=_SAME, same_mechanism=True
    )
    assert decision is TransientDecision.FAIL_FAST


def test_non_external_service_error_fails_fast():
    """Network/DependencyError/etc. are never fallback candidates."""
    for exc in (DependencyError("missing token"), ValueError("boom"), TimeoutError()):
        decision = classify_transient(
            exc, platform="medium", transition=_SAME, same_mechanism=True
        )
        assert decision is TransientDecision.FAIL_FAST


def test_empty_whitelists_make_every_5xx_and_cross_mechanism_fail_fast():
    """Belt-and-suspenders: with default empty whitelists, nothing risky passes."""
    five_xx = ExternalServiceError("HTTP 502 bad gateway")
    assert (
        classify_transient(
            five_xx, platform="anything", transition=_SAME, same_mechanism=True
        )
        is TransientDecision.FAIL_FAST
    )
    cross = ("ApiAdapter", "BrowserAdapter")
    assert (
        classify_transient(
            _pre_create_429(), platform="anything", transition=cross, same_mechanism=False
        )
        is TransientDecision.FAIL_FAST
    )
