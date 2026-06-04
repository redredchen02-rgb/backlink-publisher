from backlink_publisher.health.registry import HealthChecker, HealthResult, register


@register
class DiskAccessChecker(HealthChecker):
    @classmethod
    def slug(cls) -> str:
        return "disk_access"

    @classmethod
    def check(cls) -> HealthResult:
        from backlink_publisher.config.loader import _cache_dir, _config_dir

        config_dir = _config_dir()
        cache_dir = _cache_dir()

        issues: list[str] = []

        if not config_dir.exists():
            issues.append(f"Config dir does not exist: {config_dir}")
        else:
            try:
                probe = config_dir / ".health_write_probe"
                probe.write_text("ok")
                probe.unlink(missing_ok=True)
            except OSError as exc:
                issues.append(f"Config dir not writable: {exc}")

        if not cache_dir.exists():
            issues.append(f"Cache dir does not exist: {cache_dir}")
        else:
            try:
                probe = cache_dir / ".health_write_probe"
                probe.write_text("ok")
                probe.unlink(missing_ok=True)
            except OSError as exc:
                issues.append(f"Cache dir not writable: {exc}")

        canary_path = config_dir / "canary-health.json"
        if config_dir.exists():
            try:
                canary_path.write_text("{}")
                canary_path.unlink(missing_ok=True)
            except OSError as exc:
                issues.append(f"canary-health.json not writable: {exc}")

        if issues:
            return HealthResult(
                slug="disk_access",
                status="fail",
                message="; ".join(issues),
                details={"issues": issues},
            )
        return HealthResult(
            slug="disk_access",
            status="pass",
            message="All disk paths accessible",
        )
