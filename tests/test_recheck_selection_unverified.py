"""Unit 2 — select_unverified_candidates (plan 2026-06-05-002).

Covers _unverified_universe, select_unverified_candidates, and the combined
pool in KeepaliveJobRegistry._run_recheck.
"""
from __future__ import annotations

__tier__ = "unit"

import json
from datetime import datetime, timedelta, timezone

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.recheck.selection import (
    select_candidates,
    select_unverified_candidates,
)


def _seed_unverified(store: EventStore, live_url: str, target_url: str,
                     platform: str = "substack") -> int:
    """Add an article + publish.unverified event; return article_id."""
    store.add_article({
        "target_urls_json": json.dumps([target_url]),
        "live_url": live_url,
        "platform": platform,
    })
    rows = list(store.query(
        "SELECT article_id FROM articles WHERE live_url = ?", (live_url,)
    ))
    aid = rows[0]["article_id"]
    from backlink_publisher.events.kinds import PUBLISH_UNVERIFIED
    store.append(
        PUBLISH_UNVERIFIED,
        {"live_url": live_url, "platform": platform, "target_url": target_url},
        target_url=target_url,
        host="sub.com",
        article_id=aid,
    )
    return aid


# ── happy path ────────────────────────────────────────────────────────────────

def test_select_unverified_returns_unverified_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    store = EventStore()
    _seed_unverified(store, "https://sub.com/p1", "https://site.com/t1")

    cands = select_unverified_candidates(store, now=datetime.now())
    assert len(cands) == 1
    assert cands[0]["live_url"] == "https://sub.com/p1"


def test_select_unverified_does_not_return_confirmed(tmp_path, monkeypatch):
    """publish.confirmed events must NOT be returned by select_unverified_candidates."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    store = EventStore()
    store.add_article({
        "target_urls_json": json.dumps(["https://site.com/t2"]),
        "live_url": "https://medium.com/p2",
        "platform": "medium",
    })
    rows = list(store.query("SELECT article_id FROM articles WHERE live_url = ?",
                             ("https://medium.com/p2",)))
    aid = rows[0]["article_id"]
    from backlink_publisher.events.kinds import PUBLISH_CONFIRMED
    store.append(
        PUBLISH_CONFIRMED,
        {"live_url": "https://medium.com/p2", "platform": "medium"},
        target_url="https://site.com/t2",
        article_id=aid,
    )

    cands = select_unverified_candidates(store, now=datetime.now())
    assert cands == []


# ── retry window ──────────────────────────────────────────────────────────────

def test_select_unverified_respects_min_retry_days(tmp_path, monkeypatch):
    """A candidate probed within min_retry_days is excluded."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    store = EventStore()
    aid = _seed_unverified(store, "https://sub.com/p3", "https://site.com/t3")

    # Emit a recent link.rechecked to set last_attempt_at
    from backlink_publisher.recheck.events_io import emit_recheck
    emit_recheck(store, [{
        "verdict": "link_stripped",
        "live_url": "https://sub.com/p3",
        "article_id": aid,
    }])

    # Still within 7-day retry window
    cands = select_unverified_candidates(store, now=datetime.now(), min_retry_days=7)
    assert cands == []


def test_select_unverified_returns_after_retry_window(tmp_path, monkeypatch):
    """A candidate probed > min_retry_days ago is eligible again."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    store = EventStore()
    aid = _seed_unverified(store, "https://sub.com/p4", "https://site.com/t4")

    from backlink_publisher.recheck.events_io import emit_recheck
    emit_recheck(store, [{
        "verdict": "link_stripped",
        "live_url": "https://sub.com/p4",
        "article_id": aid,
    }])

    # Simulate now = 8 days later (past 7-day retry floor)
    future_now = datetime.now() + timedelta(days=8)
    cands = select_unverified_candidates(store, now=future_now, min_retry_days=7)
    assert len(cands) == 1


# ── cap ───────────────────────────────────────────────────────────────────────

def test_select_unverified_cap_respected(tmp_path, monkeypatch):
    """Cap of N limits candidates returned."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    store = EventStore()
    for i in range(5):
        _seed_unverified(store, f"https://sub.com/p{i+10}", f"https://site.com/t{i+10}")

    cands = select_unverified_candidates(store, now=datetime.now(), cap=3)
    assert len(cands) == 3


# ── NULL article_id fallback ──────────────────────────────────────────────────

def test_select_unverified_null_article_id_fallback(tmp_path, monkeypatch):
    """publish.unverified events with NULL article_id are recovered via live_url lookup."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    store = EventStore()
    live_url = "https://sub.com/fallback1"
    target_url = "https://site.com/fallback"

    # Add article so the fallback join can find it
    store.add_article({
        "target_urls_json": json.dumps([target_url]),
        "live_url": live_url,
        "platform": "substack",
    })
    # Emit publish.unverified with article_id=None (simulates the publish_writer path)
    from backlink_publisher.events.kinds import PUBLISH_UNVERIFIED
    store.append(
        PUBLISH_UNVERIFIED,
        {"live_url": live_url, "platform": "substack", "target_url": target_url},
        target_url=target_url,
        host="sub.com",
        article_id=None,  # NULL
    )

    cands = select_unverified_candidates(store, now=datetime.now())
    assert len(cands) == 1
    assert cands[0]["live_url"] == live_url


# ── symmetry with select_candidates ──────────────────────────────────────────

def test_select_unverified_fields_match_select_candidates(tmp_path, monkeypatch):
    """Returned dicts have the same field set as select_candidates."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    store = EventStore()
    _seed_unverified(store, "https://sub.com/sym1", "https://site.com/sym1")

    unverified_cands = select_unverified_candidates(store, now=datetime.now())
    assert unverified_cands, "expected at least one candidate"

    # Select_candidates returns empty (no publish.confirmed), but check field set
    expected_fields = {"live_url", "target_url", "host", "article_id", "platform",
                       "baseline_anchor", "published_age_days", "source"}
    actual_fields = set(unverified_cands[0].keys())
    assert expected_fields == actual_fields


# ── integration: _run_recheck processes unverified pool ──────────────────────

def test_run_recheck_processes_unverified_pool(tmp_path, monkeypatch):
    """_run_recheck includes unverified pool when candidates=None."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    import time

    from webui_app.services.keepalive_job import KeepaliveJobRegistry

    store = EventStore()
    _seed_unverified(store, "https://sub.com/u_int", "https://site.com/u_int")
    rows = list(store.query("SELECT article_id FROM articles WHERE live_url = ?",
                             ("https://sub.com/u_int",)))
    aid = rows[0]["article_id"]

    probed = []

    def probe_fn(rec):
        probed.append(rec["live_url"])
        return {**rec, "verdict": "alive", "reason": None}

    registry = KeepaliveJobRegistry()
    # candidates=None → uses default (confirmed + unverified) pool
    job = registry.start_recheck(store=store, probe_fn=probe_fn)
    for _ in range(50):
        if job.status in ("done", "error", "cancelled"):
            break
        time.sleep(0.05)

    assert job.status == "done"
    assert "https://sub.com/u_int" in probed

    # verified_at should be set after alive verdict
    rows2 = list(store.query("SELECT verified_at FROM articles WHERE article_id = ?", (aid,)))
    assert rows2[0]["verified_at"] is not None


def test_run_recheck_injected_candidates_unchanged(tmp_path, monkeypatch):
    """When candidates is injected explicitly, no unverified pool is added."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    import time

    from webui_app.services.keepalive_job import KeepaliveJobRegistry

    store = EventStore()
    _seed_unverified(store, "https://sub.com/u_noadd", "https://site.com/u_noadd")

    probed = []

    def probe_fn(rec):
        probed.append(rec["live_url"])
        return {**rec, "verdict": "alive", "reason": None}

    explicit = [{"live_url": "https://explicit.com/p", "target_url": None,
                 "host": "explicit.com", "article_id": None, "platform": None,
                 "source": "test"}]

    registry = KeepaliveJobRegistry()
    job = registry.start_recheck(store=store, candidates=explicit, probe_fn=probe_fn)
    for _ in range(50):
        if job.status in ("done", "error", "cancelled"):
            break
        time.sleep(0.05)

    assert job.status == "done"
    assert probed == ["https://explicit.com/p"]  # only explicit, not unverified
