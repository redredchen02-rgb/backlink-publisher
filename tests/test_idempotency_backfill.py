"""Unit 6 — best-effort backfill of the dedup store from publish-success events.

Conservative tiering (confirmed+mapped+live_url → done; else → uncertain),
explicit adapter-string → platform map (retired/unknown → quarantine, never a
silent drop or crash), and decision-preserving INSERT-only seeding that never
resurrects an operator-forgotten key.

Plan: docs/plans/2026-05-27-005-feat-cross-run-publish-idempotency-plan.md (U6).
"""

from __future__ import annotations

import sys
from io import StringIO

import pytest

import backlink_publisher.publishing.adapters  # noqa: F401  (triggers register())
from backlink_publisher.cli.publish_backlinks import main
from backlink_publisher.events import EventStore
from backlink_publisher.idempotency import DedupKey, DedupStore
from backlink_publisher.idempotency import audit_log
from backlink_publisher.idempotency.backfill import (
    _ADAPTER_STRING_TO_PLATFORM,
    run_backfill,
)
from backlink_publisher.publishing.registry import registered_platforms


@pytest.fixture(autouse=True)
def _fresh_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path / "cfg"))


def _event(kind, target, adapter, live_url):
    EventStore().append(
        kind,
        {"live_url": live_url, "target_url": target, "platform": adapter},
        target_url=target,
    )


# --------------------------------------------------------------------------- #
# Tiering
# --------------------------------------------------------------------------- #
def test_confirmed_mapped_seeds_done_verify_ok():
    _event("publish.confirmed", "https://x.com/a", "blogger-api", "https://blogger.com/p/1")
    r = run_backfill()
    assert r.seeded_done == 1
    rec = DedupStore().get(DedupKey(platform="blogger", target_url="https://x.com/a"))
    assert rec.state == "done"
    assert rec.verify_ok is True
    assert rec.live_url == "https://blogger.com/p/1"


def test_unverified_seeds_uncertain():
    _event("publish.unverified", "https://x.com/b", "medium-api", "https://m.com/p/2")
    r = run_backfill()
    assert r.seeded_uncertain == 1
    assert DedupStore().get(
        DedupKey(platform="medium", target_url="https://x.com/b")
    ).state == "uncertain"


def test_confirmed_missing_live_url_seeds_uncertain():
    _event("publish.confirmed", "https://x.com/c", "note", None)
    r = run_backfill()
    assert r.seeded_uncertain == 1
    assert DedupStore().get(
        DedupKey(platform="note", target_url="https://x.com/c")
    ).state == "uncertain"


@pytest.mark.parametrize(
    "adapter,platform",
    [
        ("note", "note"),
        ("txtfyi-form-post", "txtfyi"),
        ("medium-brave", "medium"),
        ("telegraph-cdp", "telegraph"),
        ("mastodon-browser-attach", "mastodon"),
    ],
)
def test_real_adapter_strings_map(adapter, platform):
    _event("publish.confirmed", f"https://x.com/{adapter}", adapter, "https://live.com/p")
    run_backfill()
    assert DedupStore().get(
        DedupKey(platform=platform, target_url=f"https://x.com/{adapter}")
    ) is not None


# --------------------------------------------------------------------------- #
# Quarantine (retired/unknown), never crash / never silent-drop
# --------------------------------------------------------------------------- #
def test_retired_adapter_string_quarantines():
    _event("publish.confirmed", "https://x.com/old", "hashnode-gql", "https://h/p")
    r = run_backfill()
    assert r.quarantined == 1
    assert r.seeded == 0


def test_unknown_adapter_string_quarantines_not_crashes():
    _event("publish.confirmed", "https://x.com/q", "totally-made-up", "https://h/p")
    r = run_backfill()  # must not raise
    assert r.quarantined == 1


def test_missing_target_url_quarantines():
    _event("publish.confirmed", None, "blogger-api", "https://b/p")
    r = run_backfill()
    assert r.quarantined == 1
    assert r.seeded == 0


# --------------------------------------------------------------------------- #
# Decision-preserving / idempotent
# --------------------------------------------------------------------------- #
def test_rerun_is_idempotent_no_overwrite():
    _event("publish.confirmed", "https://x.com/a", "blogger-api", "https://blogger.com/p/1")
    first = run_backfill()
    assert first.seeded_done == 1
    second = run_backfill()
    assert second.seeded_done == 0
    assert second.skipped_existing == 1


def test_backfill_never_resurrects_forgotten_key():
    key = DedupKey(platform="blogger", target_url="https://x.com/a")
    _event("publish.confirmed", "https://x.com/a", "blogger-api", "https://blogger.com/p/1")
    run_backfill()
    # Operator forgets the key…
    audit_log.append_entry(
        action="forget", platform=key.platform, target_url=key.target_url,
        account=key.account, from_state="done", to_state="absent", reason="mistake",
    )
    DedupStore().forget(key)
    # …re-running backfill must NOT re-seed it (decision-preserving).
    r = run_backfill()
    assert DedupStore().get(key) is None
    assert r.skipped_operator_touched == 1
    assert r.seeded_done == 0


def test_does_not_overwrite_live_run_record():
    """A key already terminal from a live run is left untouched by backfill."""
    key = DedupKey(platform="blogger", target_url="https://x.com/a")
    store = DedupStore()
    store.intent_write(key)
    store.transition(key, "failed")  # live run recorded failed
    _event("publish.confirmed", "https://x.com/a", "blogger-api", "https://blogger.com/p/1")
    run_backfill()
    assert store.get(key).state == "failed"  # not flipped to done


# --------------------------------------------------------------------------- #
# Map invariants
# --------------------------------------------------------------------------- #
def test_map_values_are_all_registered_platforms():
    assert set(_ADAPTER_STRING_TO_PLATFORM.values()) <= set(registered_platforms())


def test_every_registered_platform_is_reachable():
    """No live platform is wholesale-unmappable (its posts would all quarantine)."""
    assert set(registered_platforms()) <= set(_ADAPTER_STRING_TO_PLATFORM.values())


# --------------------------------------------------------------------------- #
# CLI verb
# --------------------------------------------------------------------------- #
def _run(argv):
    old = (sys.stdin, sys.stdout, sys.stderr)
    try:
        sys.stdin = StringIO("")
        out, err = StringIO(), StringIO()
        sys.stdout, sys.stderr = out, err
        try:
            main(argv)
            code = 0
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        return out.getvalue(), err.getvalue(), code
    finally:
        sys.stdin, sys.stdout, sys.stderr = old


def test_cli_backfill_dedup_summary_and_exit_0():
    _event("publish.confirmed", "https://x.com/a", "blogger-api", "https://blogger.com/p/1")
    _event("publish.confirmed", "https://x.com/old", "hashnode-gql", "https://h/p")
    _out, stderr, code = _run(["--backfill-dedup"])
    assert code == 0, stderr
    assert "seeded done=1" in stderr
    assert "quarantined(unmappable)=1" in stderr


def test_cli_backfill_empty_store_exits_0():
    _out, _stderr, code = _run(["--backfill-dedup"])
    assert code == 0


def test_backfill_conflicts_with_forget():
    _out, stderr, code = _run(
        ["--backfill-dedup", "--forget", "blogger", "https://x.com/a", "--reason", "x"]
    )
    assert code == 2
    assert "mutually exclusive" in stderr
