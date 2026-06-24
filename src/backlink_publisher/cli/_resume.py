"""Backward-compat shim — moved to backlink_publisher.cli.admin._resume (plan 2026-06-24-002 U8)."""
from __future__ import annotations

from backlink_publisher.cli.admin._resume import *  # noqa: F401, F403
from backlink_publisher.cli.admin._resume import item_to_publish_output, _run_resume, _ResumeLoopState, _publish_one_resume_item  # noqa: F401
