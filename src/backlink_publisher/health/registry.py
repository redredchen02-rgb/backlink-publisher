"""Health checker registry — register() pattern mirroring publishing/registry.py.

Usage:
    @register
    class MyChecker(HealthChecker):
        @classmethod
        def slug(cls) -> str: ...
        @classmethod
        def check(cls) -> HealthResult: ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class HealthResult:
    slug: str
    status: str  # "pass" | "warn" | "fail"
    message: str = ""
    details: dict[str, Any] | None = None


class HealthChecker(ABC):
    @classmethod
    @abstractmethod
    def slug(cls) -> str:
        ...

    @classmethod
    @abstractmethod
    def check(cls) -> HealthResult:
        ...


_REGISTRY: dict[str, type[HealthChecker]] = {}


def register(cls: type[HealthChecker]) -> type[HealthChecker]:
    slug = cls.slug()
    if not isinstance(slug, str) or not slug.strip():
        raise TypeError(
            f"HealthChecker {cls.__name__}.slug() must return a non-empty string"
        )
    _REGISTRY[slug.strip()] = cls
    return cls


def registered_checkers() -> list[str]:
    return sorted(_REGISTRY.keys())


def run_all() -> list[HealthResult]:
    results: list[HealthResult] = []
    for slug in sorted(_REGISTRY):
        checker_cls = _REGISTRY[slug]
        try:
            result = checker_cls.check()
        except Exception as exc:
            result = HealthResult(
                slug=slug,
                status="fail",
                message=f"Checker raised: {exc}",
                details={"error": repr(exc)},
            )
        results.append(result)
    return results
