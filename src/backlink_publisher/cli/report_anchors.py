"""Backward-compat shim — moved to backlink_publisher.cli.publish.report_anchors (plan 2026-06-24-002 U8)."""
import sys as _sys
import backlink_publisher.cli.publish.report_anchors as _real

if __name__ != "__main__":
    _sys.modules[__name__] = _real
else:
    _real.main()
