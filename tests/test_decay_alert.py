"""Unit tests for decay-alert checker (Plan 2026-06-16-002 U8)."""

from __future__ import annotations

__tier__ = "unit"

from unittest.mock import call, MagicMock


def _make_store(query_results: list[list[dict]]) -> MagicMock:
    store = MagicMock()
    store.query.side_effect = query_results
    return store


class TestDecayAlertRun:
    def test_no_rows_returns_zero(self):
        """No dead links → no alerts emitted."""
        from backlink_publisher.cli.decay_alert import run

        store = _make_store([[]])  # query 1 (dead links): empty
        assert run(store) == 0
        store.append.assert_not_called()

    def test_below_threshold_no_alert(self):
        """Only 1 distinct dead URL per target → no alert."""
        from backlink_publisher.cli.decay_alert import run

        # query 1 returns no rows (HAVING ≥ 2 not satisfied)
        store = _make_store([[]])
        assert run(store) == 0

    def test_emits_alert_for_new_target(self):
        """Target with ≥2 dead links, not yet alerted → emits decay.alert."""
        from backlink_publisher.cli.decay_alert import run

        dead_rows = [{"target_url": "https://example.com", "dead_url_count": 3}]
        alerted_rows = []  # no existing alerts
        store = _make_store([dead_rows, alerted_rows])
        result = run(store)
        assert result == 1
        store.append.assert_called_once()
        call_kwargs = store.append.call_args
        assert call_kwargs.kwargs["kind"] == "decay.alert"
        assert call_kwargs.kwargs["target_url"] == "https://example.com"
        assert call_kwargs.kwargs["payload"]["lost_count"] == 3

    def test_dedup_skips_already_alerted_target(self):
        """Target already has decay.alert in window → no duplicate emitted."""
        from backlink_publisher.cli.decay_alert import run

        dead_rows = [{"target_url": "https://example.com", "dead_url_count": 3}]
        alerted_rows = [{"target_url": "https://example.com"}]
        store = _make_store([dead_rows, alerted_rows])
        result = run(store)
        assert result == 0
        store.append.assert_not_called()

    def test_partial_dedup_emits_only_new(self):
        """Two targets: one already alerted, one new → only new gets alert."""
        from backlink_publisher.cli.decay_alert import run

        dead_rows = [
            {"target_url": "https://known.com", "dead_url_count": 2},
            {"target_url": "https://new.com", "dead_url_count": 4},
        ]
        alerted_rows = [{"target_url": "https://known.com"}]
        store = _make_store([dead_rows, alerted_rows])
        result = run(store)
        assert result == 1
        store.append.assert_called_once()
        assert store.append.call_args.kwargs["target_url"] == "https://new.com"
