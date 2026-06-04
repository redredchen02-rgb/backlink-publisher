"""R4 — adapter-string platform normalization at the ledger seam.

plan 2026-06-04-001 Unit 3. ``telegraph`` and ``telegraph-api`` are one physical
platform; un-normalized they double-count in the equity ledger / channel
scorecard. Normalization happens once, at the ledger history-join chokepoint.
"""
__tier__ = "integration"

import json

from backlink_publisher.events import EventStore
from backlink_publisher.ledger.aggregate import build_ledger
from backlink_publisher.publishing.platform_alias import (
    _ADAPTER_STRING_TO_PLATFORM,
    canonical_platform,
)

T = "https://51acgs.com/comic/117"


def _article(store, live_url, target=T):
    store.add_article({"target_urls_json": json.dumps([target]), "live_url": live_url})


# ── pure helper ────────────────────────────────────────────────────────────

def test_canonical_platform_collapses_api_variants():
    assert canonical_platform("telegraph-api") == "telegraph"
    assert canonical_platform("telegraph-cdp") == "telegraph"
    assert canonical_platform("blogger-api") == "blogger"
    assert canonical_platform("medium-browser") == "medium"


def test_canonical_platform_passes_through_unmapped_and_empty():
    # An already-bare or unknown name (and None/empty) must survive unchanged —
    # never silently dropped.
    assert canonical_platform("telegraph") == "telegraph"
    assert canonical_platform("ghpages") == "ghpages"
    assert canonical_platform("totally-unknown") == "totally-unknown"
    assert canonical_platform(None) is None
    assert canonical_platform("") == ""


def test_alias_map_reexport_is_same_object():
    # backfill re-exports the promoted map → the grep-guard test still resolves it.
    from backlink_publisher.idempotency.backfill import (
        _ADAPTER_STRING_TO_PLATFORM as backfill_map,
    )

    assert backfill_map is _ADAPTER_STRING_TO_PLATFORM


# ── integration: dedup at build_ledger ─────────────────────────────────────

def test_api_variant_does_not_double_count_platform(tmp_path):
    store = EventStore(path=tmp_path / "events.db")
    _article(store, "https://telegra.ph/a")
    _article(store, "https://taiwanmanga2026.blogspot.com/b")
    # Same physical telegraph platform surfaces under two adapter strings.
    history = [
        {"id": "h1", "platform": "telegraph", "target_url": T,
         "article_urls": ["https://telegra.ph/a"], "status": "published"},
        {"id": "h2", "platform": "telegraph-api", "target_url": T,
         "article_urls": ["https://taiwanmanga2026.blogspot.com/b"],
         "status": "published"},
    ]
    rows = build_ledger(store=store, history=history)
    row = next(r for r in rows if r.target_url == T)

    assert row.total_links == 2          # both links still present
    assert row.platform_count == 1       # collapsed from 2 → 1
    assert "telegraph" in row.platforms
    assert "telegraph-api" not in row.platforms
