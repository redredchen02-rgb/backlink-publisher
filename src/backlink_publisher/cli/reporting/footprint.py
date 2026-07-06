"""Backward-compat alias — canonical implementation is ``backlink_publisher.cli.footprint``.

Post-d1ecbb1b dedup: the flat module is the live implementation (used by
tests and sdk/_cli_runner); this path is kept for the pyproject console
entrypoint and origin-side imports. sys.modules aliasing binds both dotted
paths to one module object.
"""
import sys as _sys

import backlink_publisher.cli.footprint as _real  # noqa: F401

if __name__ != "__main__":
    _sys.modules[__name__] = _real
else:
    _real.main()
