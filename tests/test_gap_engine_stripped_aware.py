"""R1 / D1 — per-link stripped-aware keep-alive gap (plan 2026-06-04-001 Unit 6).

A gap is "a previously-live-dofollow link is now stripped", not "page has < N
links". The page-count ``plan_gap`` returns 0 when a target is numerically
satisfied even though a specific link died; ``plan_keepalive_gap`` surfaces that
dead link as a republish seed on a sticky platform, excludes still-live targets
(D6) and test-data hosts, and never treats ``probe_error`` as a gap.
"""
__tier__ = "unit"

from backlink_publisher._util.url import canonicalize_url
from backlink_publisher.gap.engine import (
    GapOptions,
    plan_gap,
    plan_keepalive_gap,
)

OPTS = GapOptions(desired=5, language="zh-CN")
_REQUIRED_SEED_KEYS = {"target_url", "platform", "main_domain", "language", "url_mode", "publish_mode"}


def _status(**verdict_counts):
    return {
        "counts": dict(verdict_counts),
        "total": sum(verdict_counts.values()),
        "last_verified": "2026-06-04T00:00:00",
    }


def _row(target, *, live_dofollow=5, platforms=("telegraph",)):
    return {
        "target_url": target,
        "live_dofollow": live_dofollow,
        "live_dofollow_platforms": list(platforms),
    }


def test_stripped_link_emits_seed_where_page_count_finds_none():
    t = "https://51acgs.com/comic/117"
    rows = [_row(t, live_dofollow=5, platforms=("telegraph",))]
    status = {canonicalize_url(t): _status(alive=4, link_stripped=1)}

    # Page-count mode: deficit = desired(5) - live_dofollow(5) = 0 → no seed.
    page_seeds, _, _ = plan_gap(rows, OPTS, active_dofollow=["blogger", "ghpages"])
    assert page_seeds == []

    # Per-link mode: the one stripped link surfaces as a sticky republish seed.
    seeds, gaps = plan_keepalive_gap(rows, status, OPTS)
    assert len(seeds) == 1
    assert seeds[0]["platform"] in ("blogger", "ghpages")
    assert seeds[0]["target_url"] == t
    assert gaps[0].stripped == 1
    assert gaps[0].channel_exhausted is False


def test_host_gone_counts_as_dead():
    t = "https://51acgs.com/comic/528"
    seeds, gaps = plan_keepalive_gap([_row(t)], {canonicalize_url(t): _status(host_gone=2)}, OPTS)
    assert gaps[0].stripped == 2
    assert len(seeds) == 2


def test_probe_error_is_not_a_gap():
    t = "https://51acgs.com/comic/5223"
    seeds, gaps = plan_keepalive_gap([_row(t)], {canonicalize_url(t): _status(alive=3, probe_error=2)}, OPTS)
    assert seeds == [] and gaps == []


def test_still_live_target_excluded_d6():
    t = "https://51acgs.com/comic/117"
    seeds, gaps = plan_keepalive_gap([_row(t)], {canonicalize_url(t): _status(alive=5)}, OPTS)
    assert seeds == [] and gaps == []


def test_never_rechecked_target_is_not_a_gap():
    t = "https://51acgs.com/comic/999"
    seeds, gaps = plan_keepalive_gap([_row(t)], {}, OPTS)  # no recheck status at all
    assert seeds == [] and gaps == []


def test_already_live_on_all_sticky_is_channel_exhausted():
    t = "https://51acgs.com/comic/117"
    rows = [_row(t, platforms=("blogger", "ghpages"))]      # live on both sticky
    status = {canonicalize_url(t): _status(link_stripped=2)}
    seeds, gaps = plan_keepalive_gap(rows, status, OPTS)
    assert seeds == []
    assert gaps[0].channel_exhausted is True
    assert gaps[0].emitted_platforms == []


def test_example_com_test_data_excluded():
    t = "https://example.com/article"
    status = {canonicalize_url(t): _status(link_stripped=3)}
    seeds, gaps = plan_keepalive_gap([_row(t, platforms=())], status, OPTS)
    assert seeds == [] and gaps == []


def test_sticky_platforms_injectable_narrows_destinations():
    # Runtime can drop ghpages (GitHub suspended) → only blogger seeds emitted.
    t = "https://51acgs.com/comic/117"
    status = {canonicalize_url(t): _status(link_stripped=3)}
    seeds, _ = plan_keepalive_gap([_row(t)], status, OPTS, sticky_platforms=("blogger",))
    assert {s["platform"] for s in seeds} == {"blogger"}
    assert len(seeds) == 3


def test_emitted_seeds_are_valid_planbacklinks_shape():
    t = "https://51acgs.com/comic/117"
    status = {canonicalize_url(t): _status(link_stripped=1)}
    seeds, _ = plan_keepalive_gap([_row(t)], status, OPTS)
    assert _REQUIRED_SEED_KEYS <= set(seeds[0])
    # same key set the page-count engine emits (round-trippable into plan-backlinks)
    page_row = {"target_url": "https://51acgs.com/x", "live_dofollow": 0,
                "live_dofollow_platforms": [], "liveness": "live"}
    page_seeds, _, _ = plan_gap([page_row], OPTS, active_dofollow=["blogger"])
    assert set(seeds[0]) == set(page_seeds[0])
