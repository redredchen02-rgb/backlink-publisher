"""Characterization tests for ``_util/http_probe.py::_triage`` (Unit 5).

``_triage`` had no direct unit coverage before this file — existing tests
(``test_platform_discovery.py``, ``test_channel_probe_ssrf.py``) mock
``probe_url`` wholesale and never exercise ``_triage``'s branch logic. These
tests pin down the current verdict/signal behavior for each distinct branch
combination, ahead of a complexity-reduction refactor (guard-clause /
helper-splitting only, no logic change).
"""
from __future__ import annotations

__tier__ = "unit"

from backlink_publisher._util.http_probe import _triage, Hit, UrlResult


def _result(hits: list[Hit]) -> list[UrlResult]:
    return [UrlResult(url="https://example.com", hits=hits)]


class TestTriageVerdicts:
    """One test per distinct verdict-selection branch."""

    def test_no_http_response_is_unreachable(self):
        hits = [
            Hit(ua="preflight-bot", status=None, error="ConnectionError: x"),
            Hit(ua="googlebot", status=None, error="ConnectionError: x"),
            Hit(ua="browser", status=None, error="ConnectionError: x"),
        ]
        verdict, signals, next_checks = _triage(_result(hits))
        assert verdict == "no-go-unreachable"
        assert any("No HTTP response" in s for s in signals)
        assert next_checks  # always populated regardless of verdict

    def test_preflight_403_and_browser_not_2xx_is_unreachable(self):
        hits = [
            Hit(ua="preflight-bot", status=403),
            Hit(ua="googlebot", status=403),
            Hit(ua="browser", status=403),
        ]
        verdict, signals, _ = _triage(_result(hits))
        assert verdict == "no-go-unreachable"
        assert any("preflight verifier UA is 403" in s for s in signals)

    def test_login_wall_forces_needs_browser_tier_even_with_2xx(self):
        hits = [
            Hit(ua="preflight-bot", status=200, looks_login_wall=True),
            Hit(ua="googlebot", status=200, looks_login_wall=True),
            Hit(ua="browser", status=200, looks_login_wall=True),
        ]
        verdict, signals, _ = _triage(_result(hits))
        assert verdict == "needs-browser-tier"
        assert any("Login wall detected" in s for s in signals)

    def test_preflight_403_but_browser_2xx_is_needs_browser_tier(self):
        hits = [
            Hit(ua="preflight-bot", status=403),
            Hit(ua="googlebot", status=403),
            Hit(ua="browser", status=200),
        ]
        verdict, signals, _ = _triage(_result(hits))
        assert verdict == "needs-browser-tier"
        assert any("preflight verifier UA is 403" in s for s in signals)

    def test_any_2xx_without_login_or_preflight_403_is_needs_canary(self):
        hits = [
            Hit(ua="preflight-bot", status=200),
            Hit(ua="googlebot", status=200),
            Hit(ua="browser", status=200),
        ]
        verdict, signals, _ = _triage(_result(hits))
        assert verdict == "needs-canary"
        assert any("2xx (HTTP-fetchable)" in s for s in signals)

    def test_no_2xx_no_login_no_preflight_403_falls_back_to_browser_tier(self):
        """Coded responses exist, but none are 2xx and preflight isn't 403'd
        (e.g. a 500 everywhere) — the final fallback branch.
        """
        hits = [
            Hit(ua="preflight-bot", status=500),
            Hit(ua="googlebot", status=500),
            Hit(ua="browser", status=500),
        ]
        verdict, signals, _ = _triage(_result(hits))
        assert verdict == "needs-browser-tier"


class TestTriageSignals:
    """Signal-construction branches independent of verdict selection."""

    def test_googlebot_403_signal_only_when_preflight_not_403(self):
        hits = [
            Hit(ua="preflight-bot", status=200),
            Hit(ua="googlebot", status=403),
            Hit(ua="browser", status=200),
        ]
        _, signals, _ = _triage(_result(hits))
        assert any("Googlebot UA hard-403'd" in s for s in signals)

    def test_googlebot_403_signal_suppressed_when_preflight_also_403(self):
        hits = [
            Hit(ua="preflight-bot", status=403),
            Hit(ua="googlebot", status=403),
            Hit(ua="browser", status=200),
        ]
        _, signals, _ = _triage(_result(hits))
        assert not any("Googlebot UA hard-403'd" in s for s in signals)

    def test_cloudflare_marker_signal(self):
        hits = [
            Hit(ua="preflight-bot", status=403, looks_cloudflare=True),
            Hit(ua="googlebot", status=403, looks_cloudflare=True),
            Hit(ua="browser", status=403, looks_cloudflare=True),
        ]
        _, signals, _ = _triage(_result(hits))
        assert any("Cloudflare/WAF challenge detected" in s for s in signals)

    def test_multiple_url_results_are_flattened(self):
        """_triage accepts a list of UrlResult (multi-URL probes) and
        flattens all hits before classifying."""
        results = [
            UrlResult(url="https://a.example.com", hits=[Hit(ua="preflight-bot", status=200)]),
            UrlResult(url="https://b.example.com", hits=[Hit(ua="browser", status=200)]),
        ]
        verdict, signals, _ = _triage(results)
        assert verdict == "needs-canary"
        assert any("2xx (HTTP-fetchable)" in s for s in signals)
