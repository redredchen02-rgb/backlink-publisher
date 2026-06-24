"""Backward-compat shim — moved to backlink_publisher.cli.publish._report_format (plan 2026-06-24-002 U8)."""
from __future__ import annotations

from backlink_publisher.cli.publish._report_format import *  # noqa: F401, F403
from backlink_publisher.cli.publish._report_format import _build_report, _build_tier_summary, _count_qualifying_anchors, _domain_label, _format_profile_report_json, _format_profile_report_markdown, _json_output, _markdown_table, _resolve_row_tier, _tier_markdown  # noqa: F401
