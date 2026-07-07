"""dispatch-backlinks — Signal-aware platform routing engine.

Plan 2026-06-03-002.
"""

from .routing import route, RouteResult
from .signals import collect_all, PlatformSignal

__all__ = [
    "route",
    "RouteResult",
    "collect_all",
    "PlatformSignal",
]
