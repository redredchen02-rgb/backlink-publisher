"""Shared channel/event constants — no CLI dependencies.

Canonical home for CHANNELS and EVENTS so domain packages (_util/errors.py,
publishing/browser_publish/dispatcher.py) can validate channel names without
importing from the cli/ layer.  cli/_bind/channels/__init__.py re-exports
from here so all existing import paths continue to work.
"""

from __future__ import annotations

CHANNELS: frozenset[str] = frozenset({"velog", "medium", "blogger"})
"""The closed set of supported binding channels. Adding a new channel
requires updating this frozenset plus shipping its recipe in
``cli/_bind/recipes/<name>.py``."""


EVENTS: frozenset[str] = frozenset({
    "channel.bind.start",
    "channel.bind.browser_ready",
    "channel.bind.login_detected",
    "channel.bind.persisted",
    "channel.bind.failed",
})
"""The closed set of RECON event names emitted on stdout JSONL by the
``bind-channel`` driver."""

__all__ = ["CHANNELS", "EVENTS"]
