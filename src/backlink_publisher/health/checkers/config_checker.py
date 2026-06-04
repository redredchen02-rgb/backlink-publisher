from backlink_publisher.health.registry import HealthChecker, HealthResult, register


@register
class ConfigIntegrityChecker(HealthChecker):
    @classmethod
    def slug(cls) -> str:
        return "config_integrity"

    @classmethod
    def check(cls) -> HealthResult:
        from backlink_publisher.config import load_config
        try:
            load_config()
        except Exception as exc:
            return HealthResult(
                slug="config_integrity",
                status="fail",
                message=f"Config parse error: {exc}",
                details={"error": repr(exc)},
            )
        return HealthResult(
            slug="config_integrity",
            status="pass",
            message="Config loaded successfully",
        )
