"""Tests for click_track.engine — GA4 query layer (Plan 2026-06-02-001).

Strategies
----------
* ``query_site`` → mock ``BetaAnalyticsDataClient`` at the ``google.analytics.data_v1beta`` boundary.
* ``handle_site`` → checks dry-run passthrough and error-surface.
* ``ClickQueryResult`` / ``ClickStats`` → dataclass shape tests.
"""
from __future__ import annotations

__tier__ = "unit"
from datetime import datetime, timezone, UTC

import pytest

from backlink_publisher.click_track.engine import (
    _classify_error,
    _parse_rows,
    ClickQueryOptions,
    ClickQueryResult,
    ClickStats,
    handle_site,
    query_site,
)
from backlink_publisher.config import ClickTrackConfig

# ── mock helpers ────────────────────────────────────────────────────────


class _FakeDimValue:
    """Minimal stand-in for ``DimensionValue``."""

    def __init__(self, value: str) -> None:
        self.value = value


class _FakeMetricValue:
    """Minimal stand-in for ``MetricValue``."""

    def __init__(self, value: str) -> None:
        self.value = value


class _FakeRow:
    """Minimal stand-in for ``RunReportResponse.Row``."""

    def __init__(self, dims: list[str], mets: list[str]) -> None:
        self.dimension_values = [_FakeDimValue(d) for d in dims]
        self.metric_values = [_FakeMetricValue(m) for m in mets]


class _FakeResponse:
    """Minimal stand-in for ``RunReportResponse``."""

    def __init__(self, rows: list[_FakeRow]) -> None:
        self.rows = rows


# ── _parse_rows ────────────────────────────────────────────────────────


class TestParseRows:
    def test_single_row(self):
        response = _FakeResponse(
            [
                _FakeRow(
                    dims=["medium.com"],
                    mets=["42", "12", "156"],
                ),
            ],
        )
        stats = _parse_rows(response, "target.example", "2026-05-01", "2026-05-08")
        assert len(stats) == 1
        s = stats[0]
        assert s.target_site == "target.example"
        assert s.source_domain == "medium.com"
        assert s.sessions == 42
        assert s.users == 12
        assert s.pageviews == 156
        assert s.window_start == "2026-05-01"
        assert s.window_end == "2026-05-08"

    def test_multiple_rows(self):
        response = _FakeResponse(
            [
                _FakeRow(dims=["medium.com"], mets=["10", "5", "30"]),
                _FakeRow(dims=["dev.to"], mets=["3", "2", "8"]),
            ],
        )
        stats = _parse_rows(response, "target.example", "2026-05-01", "2026-05-08")
        assert len(stats) == 2
        assert stats[1].source_domain == "dev.to"

    def test_empty_response(self):
        response = _FakeResponse([])
        stats = _parse_rows(response, "t", "2026-05-01", "2026-05-08")
        assert stats == []

    def test_skip_empty_row(self):
        """Rows with no dimension values are silently skipped."""
        response = _FakeResponse([_FakeRow(dims=[], mets=[])])
        stats = _parse_rows(response, "t", "2026-05-01", "2026-05-08")
        assert stats == []


# ── query_site (dependency-missing branch) ──────────────────────────────


class TestQuerySiteDependencyError:
    def test_google_analytics_not_installed(self, monkeypatch: pytest.MonkeyPatch):
        """When google-analytics-data is absent, query_site returns a
        dependency_missing error result."""
        monkeypatch.setattr(
            "backlink_publisher.click_track.engine.BetaAnalyticsDataClient",
            None,
            raising=False,
        )
        # Force ImportError by removing the module from sys.modules and
        # making the import fail.
        import sys

        monkeypatch.setitem(sys.modules, "google.analytics.data_v1beta", None)  # type: ignore[arg-type]
        monkeypatch.setitem(
            sys.modules,
            "google.analytics.data_v1beta.types",
            None,  # type: ignore[arg-type]
        )

        result = query_site("target.example", "123456789")
        assert result.target_site == "target.example"
        assert result.error_class == "dependency_missing"
        assert result.stats == []


# ── _classify_error ────────────────────────────────────────────────────


class TestClassifyError:
    def test_file_not_found(self):
        assert _classify_error(FileNotFoundError("creds.json")) == "ga4_credential_error"

    def test_generic_error(self):
        assert _classify_error(RuntimeError("boom")) == "ga4_api_error"

    def test_value_error(self):
        assert _classify_error(ValueError("bad value")) == "ga4_api_error"


# ── ClickQueryResult & ClickStats data shape ────────────────────────────


class TestDataclassShape:
    def test_click_query_result_defaults(self):
        r = ClickQueryResult(target_site="x.example")
        assert r.target_site == "x.example"
        assert r.stats == []
        assert r.error_reason is None
        assert r.error_class is None

    def test_click_stats_defaults(self):
        s = ClickStats(
            target_site="x.example",
            source_domain="medium.com",
            sessions=5,
            users=2,
            pageviews=20,
            window_start="2026-05-01",
            window_end="2026-05-08",
        )
        assert s.source_url is None  # optional field


# ── ClickQueryOptions ──────────────────────────────────────────────────


class TestClickQueryOptions:
    def test_default_window(self):
        opts = ClickQueryOptions()
        assert opts.window_days == 7
        assert opts.end_date is None
        assert opts.dry_run is False

    def test_custom_options(self):
        dt = datetime(2026, 6, 2, tzinfo=UTC)
        opts = ClickQueryOptions(window_days=14, end_date=dt, dry_run=True)
        assert opts.window_days == 14
        assert opts.end_date == dt
        assert opts.dry_run is True


# ── handle_site (orchestrator helper) ────────────────────────────────────


class FakeClickTrackConfig:
    """Minimal config stub for handle_site tests."""

    def __init__(self, credential_path: str | None = None) -> None:
        self.credential_path = credential_path
        self.property_id = "123456789"


class TestHandleSite:
    def test_dry_run_returns_empty_result(self):
        """In dry_run mode, handle_site returns a result with no stats
        and no error — it does not hit GA4."""
        cfg = FakeClickTrackConfig()
        opts = ClickQueryOptions(dry_run=True)
        result = handle_site("target.example", "123456789", config=cfg, opts=opts)  # type: ignore[arg-type]
        assert result.target_site == "target.example"
        assert result.stats == []
        assert result.error_reason is None

    def test_live_path_calls_query_site(self, monkeypatch: pytest.MonkeyPatch):
        """Non-dry-run delegates to query_site."""
        cfg = FakeClickTrackConfig()
        opts = ClickQueryOptions(dry_run=False)

        call_args: dict = {}

        def fake_query_site(
            target_site: str,
            property_id: str,
            *,
            credential_path: str | None = None,
            **kwargs: object,
        ) -> ClickQueryResult:
            call_args["target_site"] = target_site
            call_args["property_id"] = property_id
            call_args["credential_path"] = credential_path
            return ClickQueryResult(
                target_site=target_site,
                stats=[
                    ClickStats(
                        target_site=target_site,
                        source_domain="example.com",
                        sessions=1,
                        users=1,
                        pageviews=1,
                        window_start="2026-05-01",
                        window_end="2026-05-08",
                    ),
                ],
            )

        monkeypatch.setattr(
            "backlink_publisher.click_track.engine.query_site",
            fake_query_site,
        )

        result = handle_site("target.example", "123456789", config=cfg, opts=opts)  # type: ignore[arg-type]
        assert result.target_site == "target.example"
        assert len(result.stats) == 1
        assert call_args.get("credential_path") is None

    def test_passes_credential_path(self, monkeypatch: pytest.MonkeyPatch):
        """handle_site forwards credential_path from config to query_site."""
        cfg = FakeClickTrackConfig(credential_path="/tmp/ga4-creds.json")
        opts = ClickQueryOptions(dry_run=False)
        call_args: dict = {}

        def fake_query_site(
            target_site: str,
            property_id: str,
            *,
            credential_path: str | None = None,
            **kwargs: object,
        ) -> ClickQueryResult:
            call_args["credential_path"] = credential_path
            return ClickQueryResult(target_site=target_site)

        monkeypatch.setattr(
            "backlink_publisher.click_track.engine.query_site",
            fake_query_site,
        )
        handle_site("target.example", "123456789", config=cfg, opts=opts)  # type: ignore[arg-type]
        assert call_args["credential_path"] == "/tmp/ga4-creds.json"
