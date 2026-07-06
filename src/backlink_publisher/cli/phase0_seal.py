"""Backward-compat shim — moved to backlink_publisher.cli.admin.phase0_seal (plan 2026-06-24-002 U8)."""
import sys as _sys

import backlink_publisher.cli.admin.phase0_seal as _real  # noqa: F401

if __name__ != "__main__":
    _sys.modules[__name__] = _real
else:
    # main() RETURNS its exit code (it does not sys.exit) — propagate it, or
    # the pre-push hook's `exit $?` sees 0 and seal enforcement never refuses.
    _sys.exit(_real.main())
