"""Unit 3 — confirmed_dofollow signal for uncertain-platform probes
(plan 2026-06-05-002).

Covers:
- probe.py: confirmed_dofollow / confirmed_nofollow emitted correctly
- events_io.py: payload carries new fields
- aggregate.py: _load_confirmed_dofollow_urls + _classify promotion + R5 no double-count
"""
from __future__ import annotations

__tier__ = "unit"

import json

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.ledger.aggregate import (
    _classify,
    _load_confirmed_dofollow_urls,
    build_ledger,
)

# ── probe.py — emit signal ────────────────────────────────────────────────────

def _make_inspect_fn(*, page_readable=True, target_anchor_found=True,
                     target_is_nofollow=False, target_rel=None):
    def fn(live_url, target_url, *, timeout=10.0, capture_anchor_text=False):
        return {
            "page_readable": page_readable,
            "target_anchor_found": target_anchor_found,
            "target_is_nofollow": target_is_nofollow,
            "target_rel": target_rel,
            "reason": None,
        }
    return fn


def _make_fetch_fn():
    from backlink_publisher.recheck import indexability
    class FakeFacts:
        noindex = False
        soft_404 = False
        offhost_redirect = False
        http_status = 200
    def fn(url, *, timeout=10.0):
        return FakeFacts()
    return fn


def test_probe_uncertain_platform_no_nofollow_emits_confirmed_dofollow():
    """uncertain platform + anchor found + not nofollow → confirmed_dofollow=True."""
    from backlink_publisher.recheck.probe import probe_liveness

    result = probe_liveness(
        "https://substack.com/post",
        "https://target.com",
        platform="substack",
        inspect_fn=_make_inspect_fn(target_is_nofollow=False),
        fetch_fn=_make_fetch_fn(),
    )
    assert result["verdict"] == "alive"
    assert result.get("confirmed_dofollow") is True
    assert result.get("confirmed_nofollow") is not True


def test_probe_uncertain_platform_nofollow_emits_confirmed_nofollow():
    """uncertain platform + anchor found + IS nofollow → confirmed_nofollow=True (additive)."""
    from backlink_publisher.recheck.probe import probe_liveness

    result = probe_liveness(
        "https://substack.com/post",
        "https://target.com",
        platform="substack",
        inspect_fn=_make_inspect_fn(target_is_nofollow=True),
        fetch_fn=_make_fetch_fn(),
    )
    assert result["verdict"] == "alive"
    assert result.get("confirmed_nofollow") is True
    assert result.get("expected_nofollow") is True  # existing field preserved
    assert result.get("confirmed_dofollow") is not True


def test_probe_known_dofollow_platform_no_signal(monkeypatch):
    """Known dofollow platform (medium): no confirmed_dofollow emitted."""
    from backlink_publisher.recheck.probe import probe_liveness

    result = probe_liveness(
        "https://medium.com/post",
        "https://target.com",
        platform="medium",
        inspect_fn=_make_inspect_fn(target_is_nofollow=False),
        fetch_fn=_make_fetch_fn(),
    )
    assert result["verdict"] == "alive"
    assert result.get("confirmed_dofollow") is not True


def test_probe_liveness_only_no_target_no_signal():
    """No target_url → liveness only → no confirmed_dofollow (gate check)."""
    from backlink_publisher.recheck.probe import probe_liveness

    result = probe_liveness(
        "https://substack.com/post",
        "",  # no target
        platform="substack",
        inspect_fn=_make_inspect_fn(),
        fetch_fn=_make_fetch_fn(),
    )
    assert result["verdict"] == "alive"
    assert result.get("confirmed_dofollow") is not True


# ── events_io.py — payload carry ─────────────────────────────────────────────

def test_emit_recheck_carries_confirmed_dofollow(tmp_path, monkeypatch):
    """emit_recheck stores confirmed_dofollow=True in the payload."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    from backlink_publisher.events.kinds import LINK_RECHECKED
    from backlink_publisher.recheck.events_io import emit_recheck

    store = EventStore()
    result = {
        "verdict": "alive",
        "live_url": "https://substack.com/post",
        "platform": "substack",
        "target_url": "https://target.com",
        "confirmed_dofollow": True,
        "confirmed_nofollow": False,
    }
    emit_recheck(store, [result])
    rows = list(store.query(
        "SELECT payload_json FROM events WHERE kind = ?", (LINK_RECHECKED,)
    ))
    assert rows
    payload = json.loads(rows[0]["payload_json"])
    assert payload.get("confirmed_dofollow") is True
    assert payload.get("confirmed_nofollow") is False


def test_emit_recheck_absent_confirmed_dofollow_defaults_false(tmp_path, monkeypatch):
    """emit_recheck stores confirmed_dofollow=False when absent from result."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    from backlink_publisher.events.kinds import LINK_RECHECKED
    from backlink_publisher.recheck.events_io import emit_recheck

    store = EventStore()
    result = {"verdict": "alive", "live_url": "https://sub.com/p", "platform": "medium"}
    emit_recheck(store, [result])
    rows = list(store.query(
        "SELECT payload_json FROM events WHERE kind = ?", (LINK_RECHECKED,)
    ))
    payload = json.loads(rows[0]["payload_json"])
    assert payload.get("confirmed_dofollow") is False


# ── aggregate.py — _load_confirmed_dofollow_urls ─────────────────────────────

def test_load_confirmed_dofollow_urls_empty_store(tmp_path, monkeypatch):
    """Returns empty frozenset when store has no link.rechecked events."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    store = EventStore()
    result = _load_confirmed_dofollow_urls(store)
    assert result == frozenset()


def test_load_confirmed_dofollow_urls_latest_wins(tmp_path, monkeypatch):
    """Multiple events for same live_url: latest (by ts_utc+id) wins."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    from backlink_publisher.recheck.events_io import emit_recheck

    store = EventStore()
    url = "https://substack.com/post1"

    # First event: confirmed_dofollow=True
    emit_recheck(store, [{"verdict": "alive", "live_url": url, "confirmed_dofollow": True}])
    # Second (later) event: confirmed_dofollow=False (nofollow detected now)
    emit_recheck(store, [{"verdict": "alive", "live_url": url, "confirmed_dofollow": False}])

    result = _load_confirmed_dofollow_urls(store)
    # Latest says False → url NOT in set
    assert url not in result
    from backlink_publisher._util.url import canonicalize_url
    assert canonicalize_url(url) not in result


def test_load_confirmed_dofollow_urls_single_confirmed(tmp_path, monkeypatch):
    """Single event with confirmed_dofollow=True → url in set (canonicalized)."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    from backlink_publisher._util.url import canonicalize_url
    from backlink_publisher.recheck.events_io import emit_recheck

    store = EventStore()
    url = "https://substack.com/post2"
    emit_recheck(store, [{"verdict": "alive", "live_url": url, "confirmed_dofollow": True}])

    result = _load_confirmed_dofollow_urls(store)
    assert canonicalize_url(url) in result


# ── _classify — promotion ─────────────────────────────────────────────────────

def test_classify_uncertain_in_set_returns_dofollow():
    confirmed = frozenset(["https://substack.com/post3"])
    cls, ref = _classify("substack", confirmed_dofollow_urls=confirmed,
                         live_url="https://substack.com/post3")
    assert cls == "dofollow"
    assert ref is None


def test_classify_uncertain_not_in_set_returns_uncertain():
    confirmed = frozenset(["https://substack.com/other"])
    cls, ref = _classify("substack", confirmed_dofollow_urls=confirmed,
                         live_url="https://substack.com/post4")
    assert cls == "uncertain"


def test_classify_uncertain_empty_set_returns_uncertain():
    cls, ref = _classify("substack")  # default empty frozenset
    assert cls == "uncertain"


def test_classify_known_dofollow_unchanged():
    cls, ref = _classify("medium", confirmed_dofollow_urls=frozenset(["https://x.com"]))
    assert cls == "dofollow"


def test_classify_nofollow_unchanged():
    cls, ref = _classify("devto", confirmed_dofollow_urls=frozenset(["https://devto.com/p"]),
                         live_url="https://devto.com/p")
    assert cls == "nofollow"


# ── build_ledger integration — R5 no double-count ────────────────────────────

def test_build_ledger_uncertain_promoted_live_dofollow_count(tmp_path, monkeypatch):
    """Uncertain platform promoted by confirmed_dofollow → live_dofollow == 1, not 0."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    from datetime import datetime

    from backlink_publisher._util.url import canonicalize_url
    from backlink_publisher.recheck.events_io import emit_recheck

    store = EventStore()
    live_url = "https://substack.com/article-x"
    target_url = "https://mysite.com/page"

    # Seed article row
    store.add_article({
        "target_urls_json": json.dumps([target_url]),
        "live_url": live_url,
        "platform": "substack",
    })

    # Seed link.rechecked event with confirmed_dofollow=True
    emit_recheck(store, [{
        "verdict": "alive",
        "live_url": live_url,
        "platform": "substack",
        "target_url": target_url,
        "confirmed_dofollow": True,
    }])

    now_ts = datetime.now().isoformat(timespec="seconds")
    history = [{
        "id": "h1", "platform": "substack", "target_url": target_url,
        "article_urls": [live_url],
        "status": "published",
        "verified_at": now_ts,
        "verify_error": None,
    }]

    rows = build_ledger(store=store, history=history, stale_days=30)
    row = next((r for r in rows if "mysite.com" in r.target_url), None)
    assert row is not None
    assert row.live_dofollow == 1
    assert "substack" in row.live_dofollow_platforms


def test_build_ledger_r5_no_double_count(tmp_path, monkeypatch):
    """R5: uncertain link with confirmed_dofollow AND liveness=live → exactly 1 in live_dofollow."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    from datetime import datetime

    from backlink_publisher.recheck.events_io import emit_recheck

    store = EventStore()
    live_url = "https://substack.com/article-r5"
    target_url = "https://mysite.com/r5"

    store.add_article({
        "target_urls_json": json.dumps([target_url]),
        "live_url": live_url,
        "platform": "substack",
    })
    emit_recheck(store, [{
        "verdict": "alive",
        "live_url": live_url,
        "platform": "substack",
        "target_url": target_url,
        "confirmed_dofollow": True,
    }])

    now_ts = datetime.now().isoformat(timespec="seconds")
    history = [{
        "id": "h2", "platform": "substack", "target_url": target_url,
        "article_urls": [live_url],
        "status": "published",
        "verified_at": now_ts,  # liveness = live
        "verify_error": None,
    }]

    rows = build_ledger(store=store, history=history, stale_days=30)
    row = next((r for r in rows if "r5" in r.target_url), None)
    assert row is not None
    assert row.live_dofollow == 1  # exactly one, not two


def test_build_ledger_no_regression_without_confirmed_events(tmp_path, monkeypatch):
    """build_ledger with no link.rechecked events produces same result as before U3."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    from datetime import datetime

    store = EventStore()
    live_url = "https://medium.com/article-reg"
    target_url = "https://mysite.com/reg"

    store.add_article({
        "target_urls_json": json.dumps([target_url]),
        "live_url": live_url,
        "platform": "medium",
    })

    now_ts = datetime.now().isoformat(timespec="seconds")
    history = [{
        "id": "h3", "platform": "medium", "target_url": target_url,
        "article_urls": [live_url],
        "status": "published",
        "verified_at": now_ts,
        "verify_error": None,
    }]

    rows = build_ledger(store=store, history=history, stale_days=30)
    row = next((r for r in rows if "reg" in r.target_url), None)
    assert row is not None
    # medium is known dofollow, should still be 1
    assert row.live_dofollow == 1
