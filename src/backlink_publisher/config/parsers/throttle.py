"""Parser for ``[throttle.<slug>]`` per-platform delay overrides."""
from __future__ import annotations

from typing import Any

from ..._util.errors import InputValidationError


def _parse_platform_throttle(data: Any) -> dict[str, float]:
    """Parse all ``[throttle.<slug>]`` sub-tables into a slug→seconds map.

    Each sub-table must contain a ``delay_s`` key (numeric).  Sub-tables
    without ``delay_s`` are silently skipped.  A non-numeric ``delay_s``
    raises ``InputValidationError``.  Extra keys in the sub-table are ignored.
    """
    throttle_section = data.get("throttle", {})
    if not isinstance(throttle_section, dict):
        return {}
    result: dict[str, float] = {}
    for slug, cfg in throttle_section.items():
        if not isinstance(cfg, dict):
            continue
        if "delay_s" not in cfg:
            continue
        raw = cfg["delay_s"]
        try:
            result[slug] = float(raw)
        except (TypeError, ValueError):
            raise InputValidationError(
                f"[throttle.{slug}].delay_s must be a number; got {raw!r}"
            )
    return result
