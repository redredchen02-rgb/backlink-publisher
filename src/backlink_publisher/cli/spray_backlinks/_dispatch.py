"""Unit 5 — burst dispatch with platform-agnostic jitter.

Dispatches the drafted, audited batch via the documented-stable
``adapter_publish`` seam (NOT ``run_publish_loop`` / ``_publish_one_row`` — those
are coupled to argparse/state/checkpoint and already bake in the Medium-only
throttle). A spray-owned jittered, non-uniform delay separates shots; it does
NOT thread ``last_medium_success_idx``, so the Medium-only contract is untouched.

Continue-on-failure: any single-shot failure — including an AuthExpired — fails
just that shot; the burst continues. ``publish_fn``/``sleep_fn``/``rng`` are
injectable so tests never publish, sleep, or hit the network.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Spray-owned jitter bounds (seconds). Non-uniform spacing avoids a fixed-interval
# timing footprint. Bounds are wide; exact values don't matter for tests (sleep
# is injected). Kept here rather than reusing the Medium-only throttle.
_JITTER_MIN_S = 30.0
_JITTER_MAX_S = 120.0

# publish_fn: (row, mode, cfg) -> object with .status / .error (AdapterResult-like)
PublishFn = Callable[[dict[str, Any], str, Any], Any]
SleepFn = Callable[[float], None]


@dataclass
class DispatchSummary:
    # "succeeded" = adapter result was not "failed". In --mode draft these are
    # drafts, in --mode publish they are published; the bucket is mode-neutral
    # so the operator-facing summary doesn't overstate what happened.
    succeeded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    sleeps: list[float] = field(default_factory=list)

    @property
    def n_succeeded(self) -> int:
        return len(self.succeeded)

    @property
    def n_failed(self) -> int:
        return len(self.failed)


def _default_publish_fn(row: dict[str, Any], mode: str, cfg: Any) -> Any:
    from backlink_publisher.publishing.adapters import publish as adapter_publish

    return adapter_publish(
        payload={**row, "platform": row.get("platform", "")},
        mode=mode,
        config=cfg,
        dry_run=False,
    )


def _default_sleep_fn(seconds: float) -> None:
    # Reuse the publish-helpers seam so any global test patch of _do_sleep also
    # applies here; falls back to the local import if unavailable.
    from backlink_publisher.cli._publish_helpers import _do_sleep

    _do_sleep(seconds)


def dispatch_burst(
    rows: list[dict[str, Any]],
    cfg: Any,
    mode: str,
    *,
    publish_fn: PublishFn | None = None,
    sleep_fn: SleepFn | None = None,
    rng: random.Random | None = None,
    jitter_min: float = _JITTER_MIN_S,
    jitter_max: float = _JITTER_MAX_S,
) -> DispatchSummary:
    publish_fn = publish_fn or _default_publish_fn
    sleep_fn = sleep_fn or _default_sleep_fn
    rng = rng or random.Random()

    summary = DispatchSummary()
    for i, row in enumerate(rows):
        platform = row.get("platform", "")
        if i > 0:
            delay = rng.uniform(jitter_min, jitter_max)
            summary.sleeps.append(delay)
            sleep_fn(delay)
        try:
            result = publish_fn(row, mode, cfg)
        except Exception as exc:  # incl. AuthExpiredError — fail this shot, continue
            summary.failed.append((platform, f"{type(exc).__name__}: {exc}"))
            continue
        status = getattr(result, "status", None)
        if status == "failed":
            summary.failed.append((platform, getattr(result, "error", None) or "failed"))
        else:
            summary.succeeded.append(platform)
    return summary
