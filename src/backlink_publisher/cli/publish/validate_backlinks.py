"""Backward-compat alias — canonical implementation is ``backlink_publisher.cli.validate_backlinks``.

The d1ecbb1b reconciliation merge kept the local flat module as the live
implementation (it imports ``cli._validate_payload``), while origin's U8
reorg left a full stale copy at this path (importing origin-only
``validate._payload`` internals). Aliasing via ``sys.modules`` binds both
dotted paths to one module object so mocks/monkeypatches applied through
either path take effect, and eliminates the split-brain duplicate.
"""
import sys as _sys

import backlink_publisher.cli.validate_backlinks as _real  # noqa: F401

if __name__ != "__main__":
    _sys.modules[__name__] = _real
else:
    _real.main()
