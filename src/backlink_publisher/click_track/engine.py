"""GA4 Data API query engine — pure transform layer (Plan 2026-06-02-001).

Shell layer: :mod:`backlink_publisher.cli.click_track`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from backlink_publisher.click_track.store import ClickRow
from backlink_publisher.config import ClickTrackConfig

_log = logging.getLogger(__name__)

#: Maximum retry attempts for transient GA4 API errors.
_MAX_RETRIES = 3
#: Default look-back window in days for the GA4 query.
_DEFAULT_WINDOW_DAYS = 7


@dataclass
class ClickQueryOptions:
    """Operator-supplied knobs for one click-track run."""

    #: Look-back window in days from ``end_date``.
    window_days: int = _DEFAULT_WINDOW_DAYS
    #: Latest date (inclusive) for the query window; ``None`` → today (UTC).
    end_date: datetime | None = None
    #: Dry-run mode — print what would be queried but don't hit GA4 or the event store.
    dry_run: bool = False


@dataclass
class ClickStats:
    """Aggregated click statistics for a single (target_site, source_domain) pair."""

    #: Target site domain (e.g. ``your-site.com``).
    target_site: str
    #: Source domain (the publishing platform, e.g. ``medium.com``).
    source_domain: str
    #: Number of sessions driven by the source URL.
    sessions: int
    #: Number of users driven by the source URL.
    users: int
    #: Number of pageviews driven by the source URL.
    pageviews: int
    #: Start of the query window (ISO string).
    window_start: str
    #: End of the query window (ISO string).
    window_end: str
    #: The specific source URL path that was queried (when available).
    source_url: str | None = None


@dataclass
class ClickQueryResult:
    """Result of querying GA4 for one target site."""

    target_site: str
    #: Per-domain click statistics.
    stats: list[ClickStats] = field(default_factory=list)
    #: Error reason if the query failed; ``None`` on success.
    error_reason: str | None = None
    #: Human-readable error class for event classification.
    error_class: str | None = None


def query_site(
    target_site: str,
    property_id: str,
    *,
    credential_path: str | None = None,
    source_url: str | None = None,
    window_days: int = _DEFAULT_WINDOW_DAYS,
    end_date: datetime | None = None,
) -> ClickQueryResult:
    """Query GA4 Data API for referral traffic from backlink sources to *target_site*.

    Parameters
    ----------
    target_site : str
        The target site domain being queried.
    property_id : str
        GA4 property ID (numeric string like ``"123456789"``).
    credential_path : str or None
        Path to the GA4 service-account JSON key file. ``None`` = use
        ``GOOGLE_APPLICATION_CREDENTIALS`` env var.
    source_url : str or None
        Optional URL filter — only query traffic from this specific referrer.
        When ``None``, queries all traffic to the target site.
    window_days : int
        Look-back window in days (default 7).
    end_date : datetime or None
        Latest date to query. ``None`` → today (UTC).

    Returns
    -------
    ClickQueryResult
        Query result with per-channel stats or error information.
    """
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            DateRange,
            Dimension,
            FilterExpression,
            Filter,
            Metric,
            RunReportRequest,
        )
        from google.oauth2 import service_account
    except ImportError as exc:
        return ClickQueryResult(
            target_site=target_site,
            error_class="dependency_missing",
            error_reason=f"google-analytics-data not installed: {exc}",
        )

    try:
        if credential_path:
            credentials = service_account.Credentials.from_service_account_file(
                credential_path,
            )
            client = BetaAnalyticsDataClient(credentials=credentials)
        else:
            client = BetaAnalyticsDataClient()

        now = end_date or datetime.now(timezone.utc)
        start = now - timedelta(days=window_days)
        window_start_iso = start.strftime("%Y-%m-%d")
        window_end_iso = now.strftime("%Y-%m-%d")

        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[
                Dimension(name="sessionSource"),
                Dimension(name="sessionMedium"),
            ],
            metrics=[
                Metric(name="sessions"),
                Metric(name="totalUsers"),
                Metric(name="screenPageViews"),
            ],
            date_ranges=[DateRange(start_date=window_start_iso, end_date=window_end_iso)],
        )

        if source_url:
            request.dimension_filter = FilterExpression(
                filter=Filter(
                    field_name="pageReferrer",
                    string_filter=Filter.StringFilter(
                        match_type=Filter.StringFilter.MatchType.CONTAINS,
                        value=source_url,
                        case_sensitive=False,
                    ),
                ),
            )

        response = client.run_report(request)
        stats = _parse_rows(response, target_site, window_start_iso, window_end_iso)

        _log.info(
            "query_site(%s, property=%s) — %d rows, window=%dd",
            target_site,
            property_id,
            len(stats),
            window_days,
        )
        return ClickQueryResult(target_site=target_site, stats=stats)

    except Exception as exc:
        _log.warning("query_site(%s) failed: %s", target_site, exc)
        return ClickQueryResult(
            target_site=target_site,
            error_class=_classify_error(exc),
            error_reason=str(exc),
        )


def _parse_rows(
    response: object,
    target_site: str,
    window_start: str,
    window_end: str,
) -> list[ClickStats]:
    """Parse a ``RunReportResponse`` into a list of ``ClickStats``."""
    stats: list[ClickStats] = []
    for row in (getattr(response, "rows", None) or []):
        dims = [dv.value for dv in (row.dimension_values or [])]
        mets = [mv.value for mv in (row.metric_values or [])]
        if not dims or not mets:
            continue
        stats.append(
            ClickStats(
                target_site=target_site,
                source_domain=dims[0],
                sessions=int(mets[0]) if len(mets) > 0 else 0,
                users=int(mets[1]) if len(mets) > 1 else 0,
                pageviews=int(mets[2]) if len(mets) > 2 else 0,
                window_start=window_start,
                window_end=window_end,
            )
        )
    return stats


def _classify_error(exc: Exception) -> str:
    """Map an exception to a stable ``error_class`` string."""
    if isinstance(exc, FileNotFoundError):
        return "ga4_credential_error"
    try:
        from google.api_core.exceptions import GoogleAPIError

        if isinstance(exc, GoogleAPIError):
            return "ga4_api_error"
    except ImportError:
        pass
    return "ga4_api_error"


def handle_site(
    target_site: str,
    property_id: str,
    *,
    config: ClickTrackConfig,
    opts: ClickQueryOptions,
    existing: dict[str, list[ClickRow]] | None = None,
) -> ClickQueryResult:
    """Query one target site and return the result (suitable for CLI or scheduler).

    Parameters
    ----------
    target_site : str
        Target domain to query.
    property_id : str
        GA4 property ID.
    config : ClickTrackConfig
        Full click-track config (for credential_path).
    opts : ClickQueryOptions
        Query options (window, dry-run).
    existing : dict or None
        Pre-fetched existing click rows keyed by target_site (for future
        diff/delta computation). Not yet implemented.

    Returns
    -------
    ClickQueryResult
        Query result.
    """
    if opts.dry_run:
        _log.info("[dry-run] would query target_site=%s property=%s", target_site, property_id)
        return ClickQueryResult(target_site=target_site)

    return query_site(
        target_site=target_site,
        property_id=property_id,
        credential_path=config.credential_path,
        window_days=opts.window_days,
        end_date=opts.end_date,
    )
