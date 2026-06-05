"""Unit tests for ``scorecard.links.derive_links_by_channel`` — the per-link
drawer read function (Plan 2026-06-05-009 U1).

Pure, read-only: seeds ``link.rechecked`` events into a temp EventStore and asserts
the latest-verdict-per-link rows grouped by channel, the R5 data-honesty contract
(dofollow_state / anchor_drift only on positive assertion), and the R6 reserved-
domain exclusion. Keying on canonical ``live_url`` (not article_id) is exercised so
the NULL-article_id trap that ``derive_per_target_status`` falls into is proven absent.
"""
from __future__ import annotations

__tier__ = "unit"

from datetime import datetime, timedelta, timezone

import pytest

from backlink_publisher._util.url import canonicalize_url
from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import LINK_RECHECKED
from backlink_publisher.recheck import verdicts
import backlink_publisher.scorecard.links as links_mod
from backlink_publisher.scorecard.engine import UNATTRIBUTED
from backlink_publisher.scorecard.links import (
    LinkVerdictRow,
    derive_links_by_channel,
)

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
REAL = "https://51acgs.com/comic/528/"


@pytest.fixture
def store(tmp_path):
    return EventStore(path=tmp_path / "events.db")


def _append(store, *, live_url, verdict, platform="telegraph", target=REAL,
            aid=None, ts=NOW, **payload_extra):
    payload = {"verdict": verdict, "platform": platform, "live_url": live_url}
    payload.update(payload_extra)
    store.append(
        LINK_RECHECKED,
        payload,
        article_id=aid,
        target_url=target,
        ts_utc=ts.isoformat() if ts is not None else None,
    )


def _rows(result):
    """Flatten {channel: [rows]} into a {live_url: row} map for easy assertion."""
    return {r.live_url: r for rows in result.values() for r in rows}


# --------------------------------------------------------------------------- #
# Happy path + grouping + latest-per-link
# --------------------------------------------------------------------------- #


def test_groups_by_channel_and_returns_rows(store):
    _append(store, live_url="https://telegra.ph/a", verdict=verdicts.ALIVE, platform="telegraph")
    _append(store, live_url="https://x.blogspot.com/b", verdict=verdicts.LINK_STRIPPED, platform="blogger")
    result = derive_links_by_channel(store)
    assert set(result.keys()) == {"telegraph", "blogger"}
    assert isinstance(result["telegraph"][0], LinkVerdictRow)
    assert result["telegraph"][0].verdict == verdicts.ALIVE
    assert result["blogger"][0].verdict == verdicts.LINK_STRIPPED


def test_latest_verdict_per_link_wins(store):
    url = "https://telegra.ph/a"
    _append(store, live_url=url, verdict=verdicts.ALIVE, ts=NOW - timedelta(days=5))
    _append(store, live_url=url, verdict=verdicts.LINK_STRIPPED, ts=NOW - timedelta(days=1))
    rows = _rows(derive_links_by_channel(store))
    assert len(rows) == 1
    assert rows[url].verdict == verdicts.LINK_STRIPPED  # newer wins


def test_same_ts_tiebreak_higher_id_wins(store):
    url = "https://telegra.ph/a"
    same = NOW - timedelta(days=2)
    _append(store, live_url=url, verdict=verdicts.LINK_STRIPPED, ts=same)  # id 1
    _append(store, live_url=url, verdict=verdicts.ALIVE, ts=same)  # id 2 → wins
    rows = _rows(derive_links_by_channel(store))
    assert rows[url].verdict == verdicts.ALIVE


# --------------------------------------------------------------------------- #
# NULL-article_id trap (must NOT be dropped — overlay-keying, not per-target)
# --------------------------------------------------------------------------- #


def test_null_article_id_link_is_kept(store):
    # stdin/CLI-sourced recheck: article_id NULL, identified by live_url only.
    _append(store, live_url="https://telegra.ph/headless", verdict=verdicts.LINK_STRIPPED, aid=None)
    rows = _rows(derive_links_by_channel(store))
    assert "https://telegra.ph/headless" in rows  # not silently filtered out


# --------------------------------------------------------------------------- #
# R5 — data honesty: dofollow_state / anchor_drift only on positive assertion
# --------------------------------------------------------------------------- #


def test_r5_missing_target_rel_does_not_crash_and_uses_confirmed_dofollow(store):
    # target_rel is never persisted; confirmed_dofollow is the real signal.
    _append(store, live_url="https://telegra.ph/a", verdict=verdicts.ALIVE,
            confirmed_dofollow=True)
    row = _rows(derive_links_by_channel(store))["https://telegra.ph/a"]
    assert row.dofollow_state == "dofollow"


def test_r5_no_target_alive_leak_is_na(store):
    # liveness-only ALIVE (if-not-target branch): all booleans default False →
    # must be n/a, NOT a misleading "dofollow"/"no drift".
    _append(store, live_url="https://telegra.ph/a", verdict=verdicts.ALIVE)
    row = _rows(derive_links_by_channel(store))["https://telegra.ph/a"]
    assert row.dofollow_state is None
    assert row.anchor_drift is None


def test_r5_dead_row_default_anchor_drift_is_na(store):
    # LINK_STRIPPED carries anchor_drift=False by default (never measured) →
    # must render n/a, not "no drift".
    _append(store, live_url="https://telegra.ph/a", verdict=verdicts.LINK_STRIPPED,
            anchor_drift=False)
    row = _rows(derive_links_by_channel(store))["https://telegra.ph/a"]
    assert row.anchor_drift is None


def test_r5_dofollow_lost_and_nofollow_states(store):
    _append(store, live_url="https://a/1", verdict=verdicts.DOFOLLOW_LOST, platform="ghpages")
    _append(store, live_url="https://a/2", verdict=verdicts.ALIVE, platform="medium",
            confirmed_nofollow=True)
    _append(store, live_url="https://a/3", verdict=verdicts.ALIVE, platform="medium",
            expected_nofollow=True)
    rows = _rows(derive_links_by_channel(store))
    assert rows["https://a/1"].dofollow_state == "lost"
    assert rows["https://a/2"].dofollow_state == "nofollow"
    assert rows["https://a/3"].dofollow_state == "nofollow-expected"


def test_r5_positive_anchor_drift_is_shown(store):
    _append(store, live_url="https://telegra.ph/a", verdict=verdicts.ALIVE,
            anchor_drift=True)
    row = _rows(derive_links_by_channel(store))["https://telegra.ph/a"]
    assert row.anchor_drift is True


# --------------------------------------------------------------------------- #
# R6 — reserved test-domain exclusion (domain-boundary aware)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("target", [
    "https://example.com/p",          # RFC2606
    "https://blogger.example.com/p",  # subdomain of example.com
    "https://money.example/p",        # .example reserved TLD
    "https://a.example/p",            # .example reserved TLD
])
def test_r6_excludes_reserved_targets_by_default(store, target):
    _append(store, live_url="https://telegra.ph/a", verdict=verdicts.ALIVE, target=target)
    assert derive_links_by_channel(store) == {}
    # opt back in
    assert _rows(derive_links_by_channel(store, exclude_test=False))


@pytest.mark.parametrize("target", [
    "https://51acgs.com/comic/1/",  # real operator target
    "https://myexample.com/p",      # lookalike — boundary must NOT match
])
def test_r6_keeps_real_and_lookalike_targets(store, target):
    _append(store, live_url="https://telegra.ph/a", verdict=verdicts.ALIVE, target=target)
    assert _rows(derive_links_by_channel(store))


# --------------------------------------------------------------------------- #
# R4 — PROBE_ERROR rows are surfaced, not swallowed
# --------------------------------------------------------------------------- #


def test_r4_probe_error_row_is_present(store):
    _append(store, live_url="https://telegra.ph/a", verdict=verdicts.PROBE_ERROR)
    row = _rows(derive_links_by_channel(store))["https://telegra.ph/a"]
    assert row.verdict == verdicts.PROBE_ERROR


def test_empty_store_returns_empty(store):
    assert derive_links_by_channel(store) == {}


# --------------------------------------------------------------------------- #
# Channel resolution — payload platform -> plat_index -> UNATTRIBUTED
# --------------------------------------------------------------------------- #


def test_channel_falls_back_to_plat_index(store, monkeypatch):
    # No platform in payload → resolve via the live_url→platform index, mirroring
    # build_channel_scorecard's precedence.
    url = "https://telegra.ph/x"
    monkeypatch.setattr(
        links_mod, "_platform_by_live_url",
        lambda s: {canonicalize_url(url): "blogger"},
    )
    _append(store, live_url=url, verdict=verdicts.ALIVE, platform=None)
    rows = _rows(derive_links_by_channel(store))
    assert rows[url].channel == "blogger"


def test_channel_unattributed_when_unresolvable(store):
    # No platform and no plat_index entry → (unattributed), still surfaced.
    _append(store, live_url="https://telegra.ph/x", verdict=verdicts.ALIVE, platform=None)
    rows = _rows(derive_links_by_channel(store))
    assert rows["https://telegra.ph/x"].channel == UNATTRIBUTED


def test_unknown_verdict_is_skipped(store):
    _append(store, live_url="https://telegra.ph/x", verdict="teleported_to_mars")
    assert derive_links_by_channel(store) == {}


# --------------------------------------------------------------------------- #
# Determinism + serialization
# --------------------------------------------------------------------------- #


def test_rows_sorted_by_live_url_deterministically(store):
    for u in ("https://telegra.ph/c", "https://telegra.ph/a", "https://telegra.ph/b"):
        _append(store, live_url=u, verdict=verdicts.ALIVE, platform="telegraph")
    first = [r.live_url for r in derive_links_by_channel(store)["telegraph"]]
    second = [r.live_url for r in derive_links_by_channel(store)["telegraph"]]
    assert first == sorted(first)
    assert first == second  # stable across calls


def test_to_dict_round_trips_all_fields(store):
    _append(store, live_url="https://telegra.ph/x", verdict=verdicts.ALIVE, platform="telegraph")
    row = _rows(derive_links_by_channel(store))["https://telegra.ph/x"]
    d = row.to_dict()
    assert d["live_url"] == "https://telegra.ph/x"
    assert d["verdict"] == verdicts.ALIVE
    assert set(d) == {
        "live_url", "target_url", "channel", "verdict",
        "last_recheck_ts", "dofollow_state", "anchor_drift",
    }
