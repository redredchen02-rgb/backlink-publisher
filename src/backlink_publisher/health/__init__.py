"""Health checker framework — plugin-based checker registry.

Usage:
    from backlink_publisher.health import run_all

    for result in run_all():
        print(result.slug, result.status, result.message)
"""

# Auto-import built-in checkers so they register at import time.
from backlink_publisher.health.checkers import (  # noqa: F401
    config_checker,
    credential_checker,
    disk_checker,
)
from backlink_publisher.health.registry import (
    HealthChecker,
    HealthResult,
    register,
    registered_checkers,
    run_all,
)

__all__ = [
    "HealthChecker",
    "HealthResult",
    "register",
    "registered_checkers",
    "run_all",
]
