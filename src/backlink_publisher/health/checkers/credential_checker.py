from backlink_publisher.health.registry import HealthChecker, HealthResult, register


@register
class CredentialPresenceChecker(HealthChecker):
    @classmethod
    def slug(cls) -> str:
        return "credential_presence"

    @classmethod
    def check(cls) -> HealthResult:
        from backlink_publisher.config import load_config
        from backlink_publisher.publishing.registry import (
            _REGISTRY as PLATFORM_REGISTRY,
        )
        from backlink_publisher.publishing.registry import (
            registered_platforms,
        )

        try:
            config = load_config()
        except Exception as exc:
            return HealthResult(
                slug="credential_presence",
                status="warn",
                message=f"Cannot check credentials: config not loaded ({exc})",
                details={"error": repr(exc)},
            )

        available_platforms: list[str] = []
        unavailable_platforms: list[str] = []

        for platform in registered_platforms():
            entry = PLATFORM_REGISTRY.get(platform)
            if entry is None:
                unavailable_platforms.append(platform)
                continue
            any_available = any(
                p.available(config)
                for p in entry.publishers
            )
            if any_available:
                available_platforms.append(platform)
            else:
                unavailable_platforms.append(platform)

        total = len(available_platforms) + len(unavailable_platforms)
        if unavailable_platforms:
            return HealthResult(
                slug="credential_presence",
                status="warn",
                message=(
                    f"{len(available_platforms)}/{total} platforms "
                    f"have credentials available"
                ),
                details={
                    "available": available_platforms,
                    "unavailable": unavailable_platforms,
                },
            )
        return HealthResult(
            slug="credential_presence",
            status="pass",
            message=f"All {total} registered platforms have credentials",
            details={"available": available_platforms},
        )
