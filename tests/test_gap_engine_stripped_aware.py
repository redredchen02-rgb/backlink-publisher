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


def _status(*, alive_platforms=(), **verdict_counts):
    return {
        "counts": dict(verdict_counts),
        "total": sum(verdict_counts.values()),
        "last_verified": "2026-06-04T00:00:00",
        "alive_platforms": list(alive_platforms),
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


def test_accepts_ledger_row_dataclass_not_just_dict():
    # The real path passes build_ledger LedgerRow dataclasses (attribute access),
    # not dicts — regression for the row.get() AttributeError.
    from backlink_publisher.ledger.model import LedgerRow

    t = "https://51acgs.com/comic/117"
    row = LedgerRow(target_url=t, live_dofollow=5, live_dofollow_platforms=["telegraph"])
    status = {canonicalize_url(t): _status(link_stripped=1)}
    seeds, gaps = plan_keepalive_gap([row], status, OPTS, sticky_platforms=("blogger",))
    assert len(seeds) == 1 and seeds[0]["target_url"] == t
    assert gaps[0].stripped == 1


def test_malformed_port_target_is_skipped_not_raised():
    # canonicalize_url raises ValueError on a bad port (urlsplit(...).port); a
    # single malformed row must be skipped, never abort the whole batch (the
    # engine's "no raises on bad rows" contract).
    bad = "https://51acgs.com:notaport/comic/1"
    good = "https://51acgs.com/comic/117"
    status = {canonicalize_url(good): _status(link_stripped=1)}
    seeds, gaps = plan_keepalive_gap(
        [_row(bad), _row(good)], status, OPTS, sticky_platforms=("blogger",)
    )
    assert len(gaps) == 1 and gaps[0].target_url == good   # bad row silently dropped
    assert len(seeds) == 1


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


# ── U3 / D6: sticky-scoped net coverage ──────────────────────────────────────


def test_stripped_but_alive_on_sticky_is_not_a_gap():
    # A republished link confirmed alive on a sticky platform restores coverage —
    # the target leaves the gap set even though the old link is still stripped.
    t = "https://51acgs.com/comic/117"
    status = {canonicalize_url(t): _status(link_stripped=1, alive=1,
                                           alive_platforms=("blogger",))}
    seeds, gaps = plan_keepalive_gap([_row(t)], status, OPTS,
                                     sticky_platforms=("blogger",))
    assert seeds == [] and gaps == []


def test_stripped_with_alive_only_on_nonsticky_is_still_a_gap():
    # D1 preserved: a partial-strip whose surviving live link is on a NON-sticky
    # platform (telegraph) must still surface — net coverage is sticky-scoped.
    t = "https://51acgs.com/comic/117"
    status = {canonicalize_url(t): _status(link_stripped=1, alive=4,
                                           alive_platforms=("telegraph",))}
    seeds, gaps = plan_keepalive_gap([_row(t)], status, OPTS,
                                     sticky_platforms=("blogger",))
    assert len(gaps) == 1 and gaps[0].stripped == 1
    assert len(seeds) == 1 and seeds[0]["platform"] == "blogger"


def test_restripped_new_sticky_link_stays_a_gap():
    # S7 treadmill: the new sticky link was eaten immediately (latest verdict
    # stripped, not alive) → no sticky coverage → still a gap.
    t = "https://51acgs.com/comic/117"
    status = {canonicalize_url(t): _status(link_stripped=2, alive_platforms=())}
    seeds, gaps = plan_keepalive_gap([_row(t)], status, OPTS,
                                     sticky_platforms=("blogger",))
    assert len(gaps) == 1 and len(seeds) == 2


def test_net_coverage_respects_injected_sticky_roster():
    # Alive on ghpages resolves the gap only if ghpages is in the runtime sticky
    # roster; with blogger-only runtime sticky, a ghpages-alive target is NOT
    # considered covered on the active repair channel.
    t = "https://51acgs.com/comic/117"
    status = {canonicalize_url(t): _status(link_stripped=1, alive=1,
                                           alive_platforms=("ghpages",))}
    seeds, gaps = plan_keepalive_gap([_row(t)], status, OPTS,
                                     sticky_platforms=("blogger",))
    assert len(gaps) == 1   # ghpages not in active sticky roster → still a gap
