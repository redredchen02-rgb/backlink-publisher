"""Backward-compat shim — moved to backlink_publisher.cli.publish._dedup_ops (plan 2026-06-24-002 U8)."""
from __future__ import annotations

from backlink_publisher.cli.publish._dedup_ops import *  # noqa: F401, F403
from backlink_publisher.cli.publish._dedup_ops import _adjudicate_one, _do_forget, _do_list_uncertain, _parse_older_than, _resolve_to_state, _handle_dedup_ops, load_force_manifest  # noqa: F401
