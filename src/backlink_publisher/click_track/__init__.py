"""GA4 click tracking for published backlinks (Plan 2026-06-02-001).

This package queries Google Analytics 4 (GA4) Data API to measure how many
clicks / sessions each backlink article drives to the target site.

Public surface
--------------
.. autoclass:: ClickQueryOptions
.. autoclass:: ClickQueryResult
.. autoclass:: ClickStats
.. autofunction:: query_site
.. autofunction:: handle_site
"""

from __future__ import annotations

from .engine import ClickQueryOptions, ClickQueryResult, ClickStats, query_site, handle_site

__all__ = [
    "ClickQueryOptions",
    "ClickQueryResult",
    "ClickStats",
    "query_site",
    "handle_site",
]
