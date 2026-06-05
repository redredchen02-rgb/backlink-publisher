"""R3 — keep-alive status view (plan 2026-06-04-001 Unit 4).

The scorecard reads the link.rechecked time series as the liveness authority
(not the stale ledger column), per-target, bleeding pages first, with example.com
test data excluded and a staleness signal when newer publishes are unverified.
"""
__tier__ = "integration"

import json
from datetime import datetime, timedelta

import pytest

from backlink_publisher.events import EventStore
from backlink_publisher.events.kinds import LINK_RECHECKED, PUBLISH_CONFIRMED
from webui_app.services.keep_alive import build_keepalive_view

NOW = datetime(2026, 6, 4, 12, 0, 0)
RECENT = (NOW - timedelta(days=1)).isoformat(timespec="seconds")
OLD = (NOW - timedelta(days=5)).isoformat(timespec="seconds")
T_ATTN = "https://51acgs.com/comic/117"
T_OK = "https://51acgs.com/"
T_EX = "https://example.com/article"


def _article(store, live_url, target):
    return store.add_article(
        {"target_urls_json": json.dumps([target]), "live_url": live_url}
    )


def _recheck(store, *, target, article_id, verdict, ts, platform="telegraph"):
    store.append(
        LINK_RECHECKED,
        {"verdict": verdict, "live_url": "x", "platform": platform},
        target_url=target,
        article_id=article_id,
        ts_utc=ts,
    )


@pytest.fixture
def populated(tmp_path):
    s = EventStore(path=tmp_path / "events.db")
    a1 = _article(s, "https://telegra.ph/a1", T_ATTN)
    a2 = _article(s, "https://taiwanmanga2026.blogspot.com/a2", T_ATTN)
    a3 = _article(s, "https://redredchen01.github.io/a3", T_OK)
    a4 = _article(s, "https://telegra.ph/ex", T_EX)
    # T_ATTN: one alive, one stripped (latest wins over an older alive).
    _recheck(s, target=T_ATTN, article_id=a1, verdict="alive", ts=RECENT)
    _recheck(s, target=T_ATTN, article_id=a2, verdict="alive", ts=OLD)
    _recheck(s, target=T_ATTN, article_id=a2, verdict="link_stripped", ts=RECENT)
    # T_OK: healthy.
    _recheck(s, target=T_OK, article_id=a3, verdict="alive", ts=RECENT)
    # example.com test data — must be excluded.
    _recheck(s, target=T_EX, article_id=a4, verdict="alive", ts=RECENT)
    history = [
        {"id": "h1", "platform": "telegraph", "target_url": T_ATTN,
         "article_urls": ["https://telegra.ph/a1"], "verified_at": RECENT},
        {"id": "h2", "platform": "blogger", "target_url": T_ATTN,
         "article_urls": ["https://taiwanmanga2026.blogspot.com/a2"], "verified_at": RECENT},
        {"id": "h3", "platform": "ghpages", "target_url": T_OK,
         "article_urls": ["https://redredchen01.github.io/a3"], "verified_at": RECENT},
        {"id": "h4", "platform": "telegraph", "target_url": T_EX,
         "article_urls": ["https://telegra.ph/ex"], "verified_at": RECENT},
    ]
    return s, history


def test_per_target_stripped_count_and_strip_rate(populated):
    store, history = populated
    view = build_keepalive_view(store=store, history=history, now=NOW)
    attn = next(t for t in view["targets"] if t["target_url"] == T_ATTN)
    assert attn["stripped"] == 1          # latest verdict wins (link_stripped)
    assert attn["rechecked"] == 2
    assert attn["strip_rate"] == 0.5
    assert attn["needs_attention"] is True


def test_recheck_overrides_stale_ledger_liveness(populated):
    # h2's history says verified_at=RECENT (ledger would call it live), but the
    # latest recheck verdict is link_stripped → the view must show it stripped.
    store, history = populated
    view = build_keepalive_view(store=store, history=history, now=NOW)
    attn = next(t for t in view["targets"] if t["target_url"] == T_ATTN)
    assert attn["stripped"] >= 1


def test_example_com_excluded(populated):
    store, history = populated
    view = build_keepalive_view(store=store, history=history, now=NOW)
    assert all("example.com" not in t["target_url"] for t in view["targets"])


def test_bleeding_targets_sort_first(populated):
    store, history = populated
    view = build_keepalive_view(store=store, history=history, now=NOW)
    assert view["targets"][0]["target_url"] == T_ATTN   # needs-attention first
    assert view["targets"][0]["needs_attention"] is True


def test_empty_when_no_recheck_events(tmp_path):
    s = EventStore(path=tmp_path / "e.db")
    view = build_keepalive_view(store=s, history=[], now=NOW)
    assert view["is_empty"] is True
    assert view["targets"] == []


def test_stale_when_publish_newer_than_recheck(populated):
    store, history = populated
    newer = (NOW - timedelta(hours=1)).isoformat(timespec="seconds")
    store.append(PUBLISH_CONFIRMED, {"live_url": "https://telegra.ph/new"},
                 target_url=T_OK, ts_utc=newer)
    view = build_keepalive_view(store=store, history=history, now=NOW)
    assert view["stale"] is True


def test_route_renders():
    # Real path against the sandboxed (empty) store → S0-empty render, HTTP 200.
    from webui_app import create_app

    app = create_app()
    client = app.test_client()
    resp = client.get("/ce:keep-alive")
    assert resp.status_code == 200
    assert "保活".encode() in resp.data


def test_canonically_equal_raw_targets_merge_not_overwrite(tmp_path):
    # link.rechecked.target_url is stored raw — two canonically-equal raw
    # variants (here a utm-tagged twin) must MERGE into one scorecard row with
    # summed counts, not have one silently overwrite the other (which would let
    # a healthy twin mask a bleeding page — the bug review caught).
    from backlink_publisher._util.url import canonicalize_url
    from backlink_publisher.recheck.events_io import derive_per_target_status

    s = EventStore(path=tmp_path / "e.db")
    raw_a = "https://51acgs.com/comic/999"
    raw_b = "https://51acgs.com/comic/999?utm_source=x"   # canon-equal to raw_a
    a1 = _article(s, "https://telegra.ph/a1", raw_a)
    a2 = _article(s, "https://taiwanmanga2026.blogspot.com/a2", raw_b)
    _recheck(s, target=raw_a, article_id=a1, verdict="alive", ts=RECENT)
    _recheck(s, target=raw_b, article_id=a2, verdict="link_stripped", ts=RECENT)

    per = derive_per_target_status(s)
    canon = canonicalize_url(raw_a)
    assert list(per.keys()) == [canon]                   # one merged row
    assert per[canon]["total"] == 2
    assert per[canon]["counts"]["alive"] == 1
    assert per[canon]["counts"]["link_stripped"] == 1


def test_view_exposes_republish_gaps_runtime_sticky(tmp_path):
    # A stripped target with no blogger link is a republish gap; the view's S3
    # gap set must use the SAME runtime sticky roster the job uses (blogger only,
    # ghpages dropped while GitHub is suspended) — no S2↔S3 destination drift.
    s = EventStore(path=tmp_path / "e.db")
    t = "https://51acgs.com/comic/777"
    a = _article(s, "https://telegra.ph/g", t)
    _recheck(s, target=t, article_id=a, verdict="link_stripped", ts=RECENT)
    history = [{"id": "g", "platform": "telegraph", "target_url": t,
                "article_urls": ["https://telegra.ph/g"], "verified_at": RECENT}]
    view = build_keepalive_view(store=s, history=history, now=NOW)
    gap = next(g for g in view["gaps"] if g["target_url"] == t)
    assert gap["platforms"] == ["blogger"]
    assert gap["stripped"] == 1


def test_view_live_target_excluded_from_gaps(tmp_path):
    # A still-live target is never a gap; it's counted in live_excluded so S3 can
    # show "N still live, excluded" alongside the bleeding list.
    s = EventStore(path=tmp_path / "e.db")
    t = "https://51acgs.com/"
    a = _article(s, "https://redredchen01.github.io/a", t)
    _recheck(s, target=t, article_id=a, verdict="alive", ts=RECENT)
    history = [{"id": "h", "platform": "ghpages", "target_url": t,
                "article_urls": ["https://redredchen01.github.io/a"], "verified_at": RECENT}]
    view = build_keepalive_view(store=s, history=history, now=NOW)
    assert view["gaps"] == []
    assert view["live_excluded"] == 1


def test_equal_timestamp_latest_event_id_wins(tmp_path):
    # Two verdicts on one link at the SAME ts_utc — the later-written event
    # (higher events.id) must win, deterministically (mirrors overlay._is_newer).
    # Without the id tiebreak the first-inserted alive would mask the stripped.
    from backlink_publisher._util.url import canonicalize_url
    from backlink_publisher.recheck.events_io import derive_per_target_status

    s = EventStore(path=tmp_path / "e.db")
    t = "https://51acgs.com/comic/888"
    a = _article(s, "https://telegra.ph/x", t)
    same_ts = NOW.isoformat(timespec="seconds")
    _recheck(s, target=t, article_id=a, verdict="alive", ts=same_ts)
    _recheck(s, target=t, article_id=a, verdict="link_stripped", ts=same_ts)

    row = derive_per_target_status(s)[canonicalize_url(t)]
    assert row["counts"]["link_stripped"] == 1           # later write wins
    assert row["counts"]["alive"] == 0
    assert row["total"] == 1


# ── U2: per-target alive_platforms (net-coverage input) ──────────────────────


def test_alive_platforms_lists_platforms_with_latest_alive(tmp_path):
    # The platform of each link whose LATEST verdict is alive is exposed, so the
    # gap engine can tell whether a target is covered on a sticky platform.
    from backlink_publisher._util.url import canonicalize_url
    from backlink_publisher.recheck.events_io import derive_per_target_status

    s = EventStore(path=tmp_path / "e.db")
    t = "https://51acgs.com/comic/501"
    a_blog = _article(s, "https://taiwanmanga2026.blogspot.com/b", t)
    a_tele = _article(s, "https://telegra.ph/t", t)
    _recheck(s, target=t, article_id=a_blog, verdict="alive", ts=RECENT, platform="blogger")
    _recheck(s, target=t, article_id=a_tele, verdict="alive", ts=RECENT, platform="telegraph")

    row = derive_per_target_status(s)[canonicalize_url(t)]
    assert row["alive_platforms"] == ["blogger", "telegraph"]   # sorted


def test_alive_platforms_excludes_platform_whose_latest_is_stripped(tmp_path):
    # A platform's link that was alive then stripped must NOT appear — only the
    # link's freshest verdict counts (per-link, latest wins).
    from backlink_publisher._util.url import canonicalize_url
    from backlink_publisher.recheck.events_io import derive_per_target_status

    s = EventStore(path=tmp_path / "e.db")
    t = "https://51acgs.com/comic/502"
    a = _article(s, "https://taiwanmanga2026.blogspot.com/c", t)
    _recheck(s, target=t, article_id=a, verdict="alive", ts=OLD, platform="blogger")
    _recheck(s, target=t, article_id=a, verdict="link_stripped", ts=RECENT, platform="blogger")

    row = derive_per_target_status(s)[canonicalize_url(t)]
    assert row["alive_platforms"] == []                  # latest is stripped


def test_alive_platforms_empty_when_no_alive(tmp_path):
    from backlink_publisher._util.url import canonicalize_url
    from backlink_publisher.recheck.events_io import derive_per_target_status

    s = EventStore(path=tmp_path / "e.db")
    t = "https://51acgs.com/comic/503"
    a = _article(s, "https://telegra.ph/d", t)
    _recheck(s, target=t, article_id=a, verdict="link_stripped", ts=RECENT, platform="telegraph")

    row = derive_per_target_status(s)[canonicalize_url(t)]
    assert row["alive_platforms"] == []


# ── U1: republished link becomes a tracked article (reaches the scorecard) ───


def test_reverify_registers_article_so_recheck_reaches_scorecard(tmp_path, monkeypatch):
    # U1: a confirmed-alive republished link must reach derive_per_target_status.
    # Before, its recheck carried no article_id and was silently dropped.
    from backlink_publisher._util.url import canonicalize_url
    from backlink_publisher.recheck.events_io import derive_per_target_status
    from webui_app.services import keepalive_job

    s = EventStore(path=tmp_path / "e.db")
    target = "https://51acgs.com/comic/601"
    live = "https://taiwanmanga2026.blogspot.com/new"
    # hermetic probe — no network; echo the record with an alive verdict.
    monkeypatch.setattr(keepalive_job, "recheck_link",
                        lambda record, probe=True: {**record, "verdict": "alive"})

    result = {"published_url": live, "target_url": target, "platform": "blogger"}
    verdict = keepalive_job._default_reverify(result, s)
    assert verdict["verdict"] == "alive" and verdict.get("article_id")

    per = derive_per_target_status(s)[canonicalize_url(target)]
    assert per["counts"]["alive"] == 1
    assert per["alive_platforms"] == ["blogger"]   # sticky coverage now visible


def test_ensure_article_is_idempotent_on_duplicate_live_url(tmp_path):
    from webui_app.services import keepalive_job

    s = EventStore(path=tmp_path / "e.db")
    live = "https://taiwanmanga2026.blogspot.com/dup"
    kw = dict(live_url=live, target_url="https://51acgs.com/x",
              host="taiwanmanga2026.blogspot.com", platform="blogger")
    a1 = keepalive_job._ensure_article(s, **kw)
    a2 = keepalive_job._ensure_article(s, **kw)
    assert a1 is not None and a1 == a2          # second call reuses the row


def test_ensure_article_empty_url_returns_none(tmp_path):
    from webui_app.services import keepalive_job

    s = EventStore(path=tmp_path / "e.db")
    assert keepalive_job._ensure_article(
        s, live_url="", target_url="t", host="h", platform="blogger") is None


# ── U4: end-to-end net coverage through build_keepalive_view ──────────────────


def test_view_drops_target_repaired_on_sticky(tmp_path):
    # E2E: a target whose old telegraph link is stripped but which now has a
    # blogger (sticky) link confirmed alive must leave the gap set — the repair
    # is reflected at the view level the operator actually sees.
    s = EventStore(path=tmp_path / "e.db")
    t = "https://51acgs.com/comic/702"
    a_old = _article(s, "https://telegra.ph/old", t)
    a_new = _article(s, "https://taiwanmanga2026.blogspot.com/new", t)
    _recheck(s, target=t, article_id=a_old, verdict="link_stripped", ts=RECENT, platform="telegraph")
    _recheck(s, target=t, article_id=a_new, verdict="alive", ts=RECENT, platform="blogger")
    history = [{"id": "o", "platform": "telegraph", "target_url": t,
                "article_urls": ["https://telegra.ph/old"], "verified_at": RECENT}]

    view = build_keepalive_view(store=s, history=history, now=NOW)
    assert all(g["target_url"] != t for g in view["gaps"])   # repaired → not a gap


def test_view_keeps_partial_strip_on_nonsticky_as_gap(tmp_path):
    # Counterpart (D1 preserved): same shape but the surviving alive link is on a
    # NON-sticky platform — the target must STILL surface as a republish gap.
    s = EventStore(path=tmp_path / "e.db")
    t = "https://51acgs.com/comic/703"
    a_old = _article(s, "https://telegra.ph/s1", t)
    a_alive = _article(s, "https://telegra.ph/s2", t)
    _recheck(s, target=t, article_id=a_old, verdict="link_stripped", ts=RECENT, platform="telegraph")
    _recheck(s, target=t, article_id=a_alive, verdict="alive", ts=RECENT, platform="telegraph")
    history = [{"id": "s", "platform": "telegraph", "target_url": t,
                "article_urls": ["https://telegra.ph/s1"], "verified_at": RECENT}]

    view = build_keepalive_view(store=s, history=history, now=NOW)
    gap = next(g for g in view["gaps"] if g["target_url"] == t)
    assert gap["platforms"] == ["blogger"]   # still needs a sticky repair
