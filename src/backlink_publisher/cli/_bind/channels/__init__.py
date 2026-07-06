"""Channel recipe registry + CHANNELS frozenset + EVENTS.

``CHANNELS`` is the single-authority frozenset of supported browser-binding
channels. It lives in ``_util.constants`` (the leaf-level shared location)
and is re-exported here for backward compat — all old import paths work.

``EVENTS`` is the closed set of RECON event names emitted by the
``bind-channel`` CLI on stdout as JSONL and stays local (it is only
consumed by CLI code).

Plan 2026-06-24-002 U7: moved ``CHANNELS`` to ``_util.constants`` to
resolve the ``_util → cli`` layer violation.
"""

from __future__ import annotations

from backlink_publisher._util.constants import CHANNELS  # noqa: F401 — re-export

EVENTS: frozenset[str] = frozenset({
    "channel.bind.start",
    "channel.bind.browser_ready",
    "channel.bind.login_detected",
    "channel.bind.persisted",
    "channel.bind.failed",
})
"""The closed set of RECON event names emitted on stdout JSONL by the
``bind-channel`` driver. Each line is ``{"event": <member>, "ts": ISO,
"channel": <name>, ...}``; payload fields are loose, only ``event`` is
contract.

Happy-path ordering:
  1. ``channel.bind.start`` — process started, channel validated
  2. ``channel.bind.browser_ready`` — Playwright launched, login URL open
  3. ``channel.bind.login_detected`` — recipe's bound_predicate matched
  4. ``channel.bind.persisted`` — storage_state written 0600 + mark_bound

Any failure emits ``channel.bind.failed`` with an ``error_code`` payload
field (one of ``bound_predicate_timeout`` / ``playwright_launch_failed``
/ ``storage_path_traversal`` / ``persist_io_error`` /
``stream_closed_no_terminal_event``).
"""


__all__ = ["CHANNELS", "EVENTS"]
