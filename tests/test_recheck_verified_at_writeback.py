"""Unit 1 — write_verified_at writeback (plan 2026-06-05-002).

Covers write_verified_at() in events_io.py and its integration with
_run_recheck() in keepalive_job.py.
"""
from __future__ import annotations

__tier__ = "unit"

import json

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.recheck.events_io import write_verified_at


def _seed_article(store: EventStore, article_id: int, live_url: str, target_url: str) -> None:
    store.add_article({
        "target_urls_json": json.dumps([target_url]),
        "live_url": live_url,
        "platform": "substack",
    })


def _get_verified_at(store: EventStore, article_id: int) -> str | None:
    rows = list(store.query(
        "SELECT verified_at FROM articles WHERE article_id = ?", (article_id,)
    ))
    return rows[0]["verified_at"] if rows else None


# ── happy paths ───────────────────────────────────────────────────────────────

def test_write_verified_at_alive_sets_timestamp(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    store = EventStore()
    _seed_article(store, 1, "https://sub.com/p1", "https://site.com/t")
    # article_id after add_article is 1
    rows = list(store.query("SELECT article_id FROM articles"))
    aid = rows[0]["article_id"]

    result = {"verdict": "alive", "article_id": aid}
    n = write_verified_at(store, [result])

    assert n == 1
    ts = _get_verified_at(store, aid)
    assert ts is not None
    assert len(ts) == 19  # datetime.now().isoformat(timespec="seconds")


def test_write_verified_at_clears_verify_error(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    store = EventStore()
    _seed_article(store, 1, "https://sub.com/p2", "https://site.com/t")
    rows = list(store.query("SELECT article_id FROM articles"))
    aid = rows[0]["article_id"]
    # Manually set a verify_error
    with store.connect() as conn:
        conn.execute(
            "UPDATE articles SET verify_error = 'timeout' WHERE article_id = ?", (aid,)
        )
    result = {"verdict": "alive", "article_id": aid}
    write_verified_at(store, [result])

    row = list(store.query("SELECT verify_error FROM articles WHERE article_id = ?", (aid,)))[0]
    assert row["verify_error"] is None


# ── non-alive verdicts ────────────────────────────────────────────────────────

def test_write_verified_at_link_stripped_not_updated(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    store = EventStore()
    _seed_article(store, 1, "https://sub.com/p3", "https://site.com/t")
    rows = list(store.query("SELECT article_id FROM articles"))
    aid = rows[0]["article_id"]

    result = {"verdict": "link_stripped", "article_id": aid}
    n = write_verified_at(store, [result])

    assert n == 0
    assert _get_verified_at(store, aid) is None


def test_write_verified_at_probe_error_not_updated(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    store = EventStore()
    _seed_article(store, 1, "https://sub.com/p4", "https://site.com/t")
    rows = list(store.query("SELECT article_id FROM articles"))
    aid = rows[0]["article_id"]

    result = {"verdict": "probe_error", "article_id": aid}
    n = write_verified_at(store, [result])

    assert n == 0


# ── missing article_id ────────────────────────────────────────────────────────

def test_write_verified_at_no_article_id_no_error(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    store = EventStore()
    # stdin-sourced result has no article_id
    result = {"verdict": "alive", "article_id": None, "live_url": "https://x.com/p"}
    n = write_verified_at(store, [result])
    assert n == 0


# ── multiple results in one call ──────────────────────────────────────────────

def test_write_verified_at_only_alive_updated(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    store = EventStore()
    _seed_article(store, 1, "https://sub.com/p5", "https://site.com/t")
    _seed_article(store, 2, "https://sub.com/p6", "https://site.com/t")
    aids = [r["article_id"] for r in store.query("SELECT article_id FROM articles ORDER BY article_id")]

    results = [
        {"verdict": "alive", "article_id": aids[0]},
        {"verdict": "link_stripped", "article_id": aids[1]},
    ]
    n = write_verified_at(store, results)

    assert n == 1
    assert _get_verified_at(store, aids[0]) is not None
    assert _get_verified_at(store, aids[1]) is None


# ── integration: keepalive _run_recheck → articles.verified_at ───────────────

def test_run_recheck_alive_writes_verified_at(tmp_path, monkeypatch):
    """After _run_recheck completes with alive, articles.verified_at is set."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    import time

    from webui_app.services.keepalive_job import KeepaliveJobRegistry

    store = EventStore()
    _seed_article(store, 1, "https://sub.com/integration1", "https://site.com/t")
    rows = list(store.query("SELECT article_id FROM articles"))
    aid = rows[0]["article_id"]

    candidate = {
        "live_url": "https://sub.com/integration1",
        "target_url": "https://site.com/t",
        "host": "sub.com",
        "article_id": aid,
        "platform": "substack",
        "source": "events",
    }

    def probe_fn(rec):
        return {**rec, "verdict": "alive", "reason": None}

    registry = KeepaliveJobRegistry()
    job = registry.start_recheck(
        store=store,
        candidates=[candidate],
        probe_fn=probe_fn,
    )
    for _ in range(50):
        if job.status in ("done", "error", "cancelled"):
            break
        time.sleep(0.05)

    assert job.status == "done"
    assert _get_verified_at(store, aid) is not None


def test_verified_at_makes_ledger_live(tmp_path, monkeypatch):
    """build_ledger returns liveness='live' when history item has verified_at."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    from datetime import datetime

    from backlink_publisher.ledger import build_ledger

    store = EventStore()
    _seed_article(store, 1, "https://sub.com/p_live", "https://site.com/t")

    now_ts = datetime.now().isoformat(timespec="seconds")
    history = [{
        "id": "h1", "platform": "substack", "target_url": "https://site.com/t",
        "article_urls": ["https://sub.com/p_live"],
        "status": "published",
        "verified_at": now_ts,
        "verify_error": None,
    }]
    ledger_rows = build_ledger(store=store, history=history, stale_days=30)
    target_row = next((r for r in ledger_rows if "site.com/t" in r.target_url), None)
    assert target_row is not None
    assert target_row.liveness == "live"
