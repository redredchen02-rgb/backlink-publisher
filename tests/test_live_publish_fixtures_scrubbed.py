"""R8 security guard: live-publish fixtures carry no session-class secrets.

`scrub_text` alone is INSUFFICIENT here for two reasons the plan calls out:
  (a) it truncates inputs > _MAX_SCRUB_LEN and silently drops secrets past the
      cap — and live-page HTML routinely exceeds 64 KiB, so a tail cookie would
      pass a scrub_text-only check (a truncation false-green); and
  (b) short session ids / CSRF tokens fall below its high-entropy threshold.

This guard therefore (1) fails any fixture larger than _MAX_SCRUB_LEN, (2)
rejects Set-Cookie / Cookie / Authorization headers (case-insensitive) and
named refresh_token / session / sid / csrf / xsrf values by scanning the WHOLE
file, and (3) additionally asserts scrub_text reports zero hits. A regression
case proves the guard catches a tail cookie past the truncation cap that
scrub_text alone would miss.
"""

from __future__ import annotations

__tier__ = "unit"

from pathlib import Path
import re

import pytest

from backlink_publisher.events.scrubber import _MAX_SCRUB_LEN, scrub_text

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "live_publish"

# Named session secrets followed by a non-trivial value (case-insensitive).
_SESSION_RE = re.compile(
    r"(?i)\b(?:refresh_token|access_token|session(?:id)?|sid|csrf|xsrf)"
    r"['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9._\-+/=]{6,}"
)
_HEADER_NEEDLES = ("set-cookie:", "cookie:", "authorization:")


def _guard_violations(content: str) -> list[str]:
    """Return all secret-exposure reasons a fixture violates (empty = clean).

    Scans the WHOLE content (not a truncated prefix) so a secret living past the
    _MAX_SCRUB_LEN cap cannot slip through as a truncation false-green.
    """
    violations: list[str] = []
    if len(content) > _MAX_SCRUB_LEN:
        violations.append(
            f"exceeds _MAX_SCRUB_LEN ({len(content)} > {_MAX_SCRUB_LEN}) — a tail "
            f"secret would survive scrub_text's truncation"
        )
    lowered = content.lower()
    for needle in _HEADER_NEEDLES:
        if needle in lowered:
            violations.append(f"contains a '{needle}' header (case-insensitive)")
    if _SESSION_RE.search(content):
        violations.append("contains a session/refresh/csrf token value")
    return violations


def _fixture_files() -> list[Path]:
    return sorted(p for p in _FIXTURES.glob("*") if p.is_file())


def test_fixtures_exist():
    assert _fixture_files(), "no live_publish fixtures found to guard"


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_fixture_has_no_secrets(path: Path):
    content = path.read_text(encoding="utf-8")
    assert _guard_violations(content) == [], f"{path.name}: {_guard_violations(content)}"
    # Belt-and-suspenders: scrub_text must find no NAMED secret pattern. The
    # high-entropy fallback false-positives on long URLs (a documented heuristic
    # limit, not a secret), so it is excluded — the named patterns are the real
    # secret signal.
    _, hits = scrub_text(content)
    named = {k: v for k, v in hits.items() if k != "high_entropy"}
    assert named == {}, f"{path.name}: scrub_text flagged named secrets {named}"


def test_guard_catches_tail_cookie_past_truncation():
    """Regression: a fixture with a Set-Cookie past the 64 KiB cap MUST fail the
    guard, even though scrub_text alone (which truncates) would miss it."""
    bad = ("<p>filler</p>\n" * 6000) + "\nSet-Cookie: sid=deadbeefsecret123; Path=/\n"
    assert len(bad) > _MAX_SCRUB_LEN

    # The guard catches it (length + whole-file header scan).
    violations = _guard_violations(bad)
    assert any("Set-Cookie" in v or "set-cookie" in v for v in violations)
    assert any("_MAX_SCRUB_LEN" in v for v in violations)

    # ...whereas scrub_text alone truncates the tail and reports the cookie as
    # clean — exactly the false-green the guard exists to close.
    _, hits = scrub_text(bad)
    assert "cookie_header" not in hits


def test_guard_rejects_session_token_value():
    assert _guard_violations('{"refresh_token": "abc123def456"}')
    assert _guard_violations("Authorization: Bearer xyz")
    assert _guard_violations("COOKIE: sid=abc")        # case-insensitive
    assert _guard_violations("plain article text") == []
