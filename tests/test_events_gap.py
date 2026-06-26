"""Tests for backlink_publisher.gap.events_gap (U1.2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, UTC

from backlink_publisher.gap.events_gap import find_gaps, GapResult, PipelineGap


def _make_store(tmp_path, rows: list[dict]) -> object:
    """Create an EventStore backed by a temporary SQLite db.

    Each row may carry ``ts_utc`` to simulate historical events, plus
    ``payload`` dict (must include any REQUIRED_FIELDS for the event kind).
    """
    from backlink_publisher.events.store import EventStore

    db_path = tmp_path / "test-events.db"
    store = EventStore(path=db_path)

    for row in rows:
        payload = row.get("payload", {})
        store.append(
            kind=row["kind"],
            target_url=row.get("target_url", ""),
            payload=payload,
            ts_utc=row.get("ts_utc"),
        )
    return store


NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=UTC)


def _ts(delta_hours: float) -> str:
    """Return ISO-8601 timestamp offset from NOW by *delta_hours* (negative = past)."""
    return (NOW + timedelta(hours=delta_hours)).isoformat()


class TestFindGaps:
    def test_empty_store(self, tmp_path) -> None:
        store = _make_store(tmp_path, [])
        result = find_gaps(store, now=NOW)
        assert result.total_targets_scanned == 0
        assert result.gaps == []

    def test_target_with_fresh_intent(self, tmp_path) -> None:
        """Recent publish.intent + fresh confirm → up-to-date."""
        store = _make_store(tmp_path, [
            {"kind": "publish.intent", "target_url": "https://example.com/a",
             "payload": {"target_url": "https://example.com/a"},
             "ts_utc": _ts(-1)},
            {"kind": "publish.confirmed", "target_url": "https://example.com/a",
             "payload": {"live_url": "https://bp.com/a"},
             "ts_utc": _ts(-1)},
        ])
        result = find_gaps(store, now=NOW, intent_stale_hours=48,
                           confirm_stale_hours=168)
        assert result.total_targets_scanned == 1
        assert result.gaps == []

    def test_target_with_stale_intent(self, tmp_path) -> None:
        """Old publish.intent → stale_intent gap."""
        store = _make_store(tmp_path, [
            {"kind": "publish.intent", "target_url": "https://example.com/b",
             "payload": {"target_url": "https://example.com/b"},
             "ts_utc": _ts(-72)},
        ])
        result = find_gaps(store, now=NOW, intent_stale_hours=48,
                           confirm_stale_hours=168)
        assert len(result.gaps) == 1
        gap = result.gaps[0]
        assert gap.target_url == "https://example.com/b"
        assert gap.gap_type == "stale_intent"
        assert gap.hours_since_intent is not None and gap.hours_since_intent > 48
        assert result.skipped_stale_intent == 1

    def test_target_with_stale_confirm(self, tmp_path) -> None:
        """Old publish.confirmed → stale_confirm gap, intent not stale."""
        store = _make_store(tmp_path, [
            {"kind": "publish.intent", "target_url": "https://example.com/c",
             "payload": {"target_url": "https://example.com/c"},
             "ts_utc": _ts(-12)},
            {"kind": "publish.confirmed", "target_url": "https://example.com/c",
             "payload": {"live_url": "https://bp.com/c"},
             "ts_utc": _ts(-336)},  # 14 days
        ])
        result = find_gaps(store, now=NOW, intent_stale_hours=480,
                           confirm_stale_hours=168)
        assert len(result.gaps) == 1
        gap = result.gaps[0]
        assert gap.target_url == "https://example.com/c"
        assert gap.gap_type == "stale_confirm"
        assert result.skipped_stale_confirm == 1

    def test_no_history(self, tmp_path) -> None:
        """Target only has events that aren't intent/confirm → no_history gap."""
        store = _make_store(tmp_path, [
            {"kind": "pipeline.started", "target_url": "https://example.com/d",
             "payload": {"trigger_reason": "test"}},
        ])
        result = find_gaps(store, now=NOW)
        actual = [g.target_url for g in result.gaps if g.gap_type == "no_history"]
        assert "https://example.com/d" in actual

    def test_both_stale(self, tmp_path) -> None:
        """Both intent and confirm stale → both gap."""
        store = _make_store(tmp_path, [
            {"kind": "publish.intent", "target_url": "https://example.com/e",
             "payload": {"target_url": "https://example.com/e"},
             "ts_utc": _ts(-336)},
            {"kind": "publish.confirmed", "target_url": "https://example.com/e",
             "payload": {"live_url": "https://bp.com/e"},
             "ts_utc": _ts(-336)},
        ])
        result = find_gaps(store, now=NOW, intent_stale_hours=48,
                           confirm_stale_hours=168)
        assert len(result.gaps) == 1
        assert result.gaps[0].gap_type == "both"
        assert result.skipped_stale_intent == 1
        assert result.skipped_stale_confirm == 1

    def test_custom_thresholds(self, tmp_path) -> None:
        """Custom hour thresholds are respected."""
        store = _make_store(tmp_path, [
            {"kind": "publish.intent", "target_url": "https://example.com/f",
             "payload": {"target_url": "https://example.com/f"},
             "ts_utc": _ts(-24)},
        ])
        result = find_gaps(store, now=NOW, intent_stale_hours=23,
                           confirm_stale_hours=168)
        assert len(result.gaps) == 1
        assert result.gaps[0].gap_type == "stale_intent"

    def test_rechecked_event_counts_as_confirm(self, tmp_path) -> None:
        """link.rechecked satisfies the confirm staleness check."""
        store = _make_store(tmp_path, [
            {"kind": "publish.intent", "target_url": "https://example.com/g",
             "payload": {"target_url": "https://example.com/g"},
             "ts_utc": _ts(-720)},  # 30 days
            {"kind": "link.rechecked", "target_url": "https://example.com/g",
             "payload": {"verdict": "still_dofollow"},
             "ts_utc": _ts(-2)},  # 2 hours ago
        ])
        result = find_gaps(store, now=NOW, intent_stale_hours=24,
                           confirm_stale_hours=168)
        assert len(result.gaps) == 1

    def test_pipeline_gap_summary(self) -> None:
        """PipelineGap.summary produces expected one-liner."""
        gap = PipelineGap(
            target_url="https://x.com/page",
            host="x.com",
            gap_type="stale_intent",
            last_intent_ts="2026-06-09T00:00:00Z",
            hours_since_intent=60,
        )
        s = gap.summary
        assert "target=https://x.com/page" in s
        assert "gap=stale_intent" in s
        assert "intent=60h" in s

    def test_gap_result_defaults(self) -> None:
        """GapResult default constructor."""
        gr = GapResult()
        assert gr.gaps == []
        assert gr.total_targets_scanned == 0
        assert gr.skipped_stale_intent == 0
        assert gr.skipped_stale_confirm == 0
