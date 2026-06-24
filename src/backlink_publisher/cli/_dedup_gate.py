"""Backward-compat shim — moved to backlink_publisher.cli.publish._dedup_gate (plan 2026-06-24-002 U8)."""
from __future__ import annotations

from backlink_publisher.cli.publish._dedup_gate import *  # noqa: F401, F403
from backlink_publisher.cli.publish._dedup_gate import gate, record_done, record_failure, is_crashed_in_flight, enforce_enabled, enforce_precondition_or_exit, gate_with_force, _key_for_row  # noqa: F401
