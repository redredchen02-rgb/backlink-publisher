"""Per-link drawer reader — the micro layer under the per-channel scorecard.

``derive_links_by_channel`` returns, for each channel, the latest ``link.rechecked``
verdict of every published link grouped under it (Plan 2026-06-05-009 U1). Read-only.

Channel resolution mirrors :func:`scorecard.engine.build_channel_scorecard` exactly
(payload ``platform`` first, then the ``canonical live_url → platform`` index, then
``(unattributed)``) so the drawer and the scorecard can never disagree on which
channel a link belongs to. The latest-verdict-per-link scan is the *shared*
:func:`recheck.latest_verdicts.latest_link_verdicts` — keyed on canonical ``live_url``
so NULL-article_id (stdin/CLI) rechecks are surfaced, not dropped.

Data-honesty contract (R5): the persisted ``link.rechecked`` payload does **not**
carry the target's raw ``rel`` (``emit_recheck`` drops it). ``dofollow_state`` is
therefore derived only from the booleans that ARE persisted and only when one is
positively asserted — otherwise ``None``/n-a. This naturally suppresses the
liveness-only ALIVE case (``if not target`` in ``probe.py``, all booleans default
False) where nothing about the backlink's rel was actually observed. Likewise
``anchor_drift`` is surfaced only when positively ``True`` — a default ``False`` on a
dead/uninspected row is reported as "unknown" (``None``), never as "no drift".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

from backlink_publisher.events import EventStore
from backlink_publisher.recheck import verdicts
from backlink_publisher.recheck.latest_verdicts import (
    _canon_target,
    latest_link_verdicts,
)

from .engine import _platform_by_live_url, UNATTRIBUTED

#: RFC2606 / RFC6761 reserved names. Production events.db contamination is
#: ``example.com`` (+ subdomains); the rest are defensive and make the unit-test
#: domain zoo (``money.example`` etc.) meaningful without risking a real domain.
_RESERVED_SECOND_LEVEL = ("example.com", "example.net", "example.org")
_RESERVED_TLDS = (".example", ".test", ".invalid", ".localhost")


@dataclass
class LinkVerdictRow:
    """One published link's latest liveness state, for the drawer.

    ``dofollow_state`` ∈ {``"dofollow"``, ``"nofollow"``, ``"nofollow-expected"``,
    ``"lost"``, ``None``}; ``anchor_drift`` is ``True`` only when positively
    detected, else ``None`` (never ``False`` — see module docstring).
    """

    live_url: str | None
    target_url: str | None
    channel: str
    verdict: str
    last_recheck_ts: str | None
    dofollow_state: str | None
    anchor_drift: bool | None

    def to_dict(self) -> dict:
        return asdict(self)


def _host(url: object) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return host.lower() if host else None


def _is_reserved_test_target(url: object) -> bool:
    """True if ``url``'s host is an RFC2606/6761 reserved/test domain.

    Domain-boundary aware: matches ``example.com`` and ``*.example.com`` but NOT
    ``myexample.com``; matches the ``.example`` reserved TLD (``money.example``).
    """
    host = _host(url)
    if host is None:
        return False
    for base in _RESERVED_SECOND_LEVEL:
        if host == base or host.endswith("." + base):
            return True
    return any(host.endswith(tld) for tld in _RESERVED_TLDS)


def _dofollow_state(payload: dict) -> str | None:
    """Derive a displayable dofollow state from the persisted booleans only.

    ``None`` whenever the payload makes no positive assertion — which includes the
    liveness-only ALIVE case where the backlink's rel was never inspected.
    """
    if payload.get("verdict") == verdicts.DOFOLLOW_LOST:
        return "lost"
    if payload.get("confirmed_dofollow"):
        return "dofollow"
    if payload.get("confirmed_nofollow"):
        return "nofollow"
    if payload.get("expected_nofollow"):
        return "nofollow-expected"
    return None


def derive_links_by_channel(
    store: EventStore | None = None, *, exclude_test: bool = True
) -> dict[str, list[LinkVerdictRow]]:
    """Latest ``link.rechecked`` verdict per published link, grouped by channel.

    Read-only. Unrecognized verdicts are dropped (never invented into a row).
    When ``exclude_test`` (default) reserved/test-domain targets are filtered out
    so real backlinks are not drowned by ``example.com`` fixtures.
    """
    store = store or EventStore()
    latest, _unkeyable = latest_link_verdicts(store)
    plat_index = _platform_by_live_url(store)

    out: dict[str, list[LinkVerdictRow]] = {}
    for lv in latest.values():
        payload = lv.payload
        verdict = payload.get("verdict")
        if verdict not in verdicts.VERDICTS:
            continue
        if exclude_test and _is_reserved_test_target(lv.target_url):
            continue
        live_url = payload.get("live_url")
        canon = _canon_target(live_url)
        platform = payload.get("platform")
        channel = platform or (plat_index.get(canon) if canon else None) or UNATTRIBUTED
        out.setdefault(channel, []).append(
            LinkVerdictRow(
                live_url=live_url if isinstance(live_url, str) else None,
                target_url=lv.target_url if isinstance(lv.target_url, str) else None,
                channel=channel,
                verdict=verdict,
                last_recheck_ts=lv.ts.isoformat() if lv.ts is not None else None,
                dofollow_state=_dofollow_state(payload),
                anchor_drift=True if payload.get("anchor_drift") else None,
            )
        )

    # Deterministic order within each channel (R8-style stable output).
    for rows in out.values():
        rows.sort(key=lambda r: (r.live_url or ""))
    return out
