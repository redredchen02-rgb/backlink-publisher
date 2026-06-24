"""Backward-compat shim — moved to backlink_publisher.cli.admin.state_backup (plan 2026-06-24-002 U8)."""
from __future__ import annotations

from backlink_publisher.cli.admin.state_backup import *  # noqa: F401, F403
from backlink_publisher.cli.admin.state_backup import backup_main, restore_main  # noqa: F401
