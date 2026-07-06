"""Backward-compat alias — canonical implementation is ``backlink_publisher.cli._resume``.

The d1ecbb1b reconciliation merge kept the local flat module as the live
implementation (``cli.publish_backlinks`` imports ``_run_resume`` from it),
while origin's U8 reorg tests patch this ``cli.admin._resume`` path.
Aliasing via ``sys.modules`` binds both dotted paths to one module object
so mocks/monkeypatches applied through either path take effect.
"""
import sys as _sys

import backlink_publisher.cli._resume as _real  # noqa: F401

_sys.modules[__name__] = _real
