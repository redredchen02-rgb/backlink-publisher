"""Backward-compat alias — canonical implementation is ``backlink_publisher.cli._publish_cli``.

See ``cli/publish/_publish_helpers.py`` for why: the d1ecbb1b reconciliation
merge kept the flat module live; this alias binds the U8 ``cli.publish`` path
and the flat path to one module object so patches apply through either path.
"""
import sys as _sys

import backlink_publisher.cli._publish_cli as _real  # noqa: F401

_sys.modules[__name__] = _real
