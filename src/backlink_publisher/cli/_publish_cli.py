"""Backward-compat shim — moved to backlink_publisher.cli.publish._publish_cli (plan 2026-06-24-002 U8)."""
from __future__ import annotations

from backlink_publisher.cli.publish._publish_cli import *  # noqa: F401, F403
from backlink_publisher.cli.publish._publish_cli import _build_parser, _handle_auth_expired, _handle_checkpoint_ops  # noqa: F401
