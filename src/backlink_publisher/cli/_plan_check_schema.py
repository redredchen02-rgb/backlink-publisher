"""Backward-compat shim — moved to backlink_publisher.cli.plan._plan_check_schema (plan 2026-06-24-002 U8)."""
import sys as _sys
import backlink_publisher.cli.plan._plan_check_schema as _real  # noqa: F401

if __name__ != "__main__":
    _sys.modules[__name__] = _real
