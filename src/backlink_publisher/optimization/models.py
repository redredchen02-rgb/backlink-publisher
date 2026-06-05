"""Data models for the optimization subsystem.

Defines the schema for ``optimization_state.json`` and the rule-evaluation
result type used by the rules engine.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AdjustmentEntry:
    """One recorded weight adjustment applied by a rule."""

    rule: str
    applied_at: str  # ISO-8601 timestamp
    multiplier: float
    reason: str


@dataclass
class PlatformWeight:
    """Dispatch-weight state for a single platform."""

    base: float
    current: float
    updated_at: str  # ISO-8601 timestamp
    adjustments: list[AdjustmentEntry] = field(default_factory=list)


@dataclass
class PlatformStats:
    """Aggregated publishing-outcome statistics for a single platform."""

    total_published: int = 0
    alive_count: int = 0
    dofollow_count: int = 0
    drift_count: int = 0
    last_recheck: str | None = None  # ISO-8601 timestamp


@dataclass
class RuleConfig:
    """Configuration parameters for a single rule."""

    enabled: bool = True
    multiplier: float = 0.5
    max_strikes: int = 3
    cooldown_days: int = 7
    min_confirmations: int = 2
    max_cap: float = 3.0


@dataclass
class OptimizationStateData:
    """Top-level schema for ``optimization_state.json``."""

    version: int = 1
    weights: dict[str, Any] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    rules: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleResult:
    """Outcome of evaluating a single rule against a single platform."""

    platform: str
    rule_name: str
    old_weight: float
    new_weight: float
    multiplier: float
    reason: str
    applied: bool


def default_state() -> dict:
    """Return the default empty optimization state."""
    return {
        "version": 1,
        "weights": {},
        "stats": {},
        "rules": {
            "canary_drift": {
                "enabled": True,
                "multiplier": 0.5,
                "max_strikes": 3,
                "cooldown_days": 7,
            },
            "recheck_survival": {
                "enabled": True,
                "multiplier": 1.2,
                "max_cap": 3.0,
                "min_confirmations": 2,
            },
            "aggregated_stats": {
                "enabled": True,
                "multiplier": 0.5,
                "survival_low_threshold": 0.3,
                "dofollow_low_threshold": 0.2,
                "min_confirmations": 2,
                "min_weight": 0.1,
            },
        },
    }


def now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
