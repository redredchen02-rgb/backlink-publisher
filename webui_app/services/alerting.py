"""Alerting system — Plan 2026-06-10-002 U4.3.

In-memory alert registry with severity levels. Alerts are created by pipeline
steps, health checks, and credential audits, and surfaced on the WebUI
``/ce:health`` page as dashboard cards.

Levels:
    INFO     — pipeline run completed / no gaps (auto-dismiss banner)
    WARN     — platform survival < 30 % / publish failure rate > 20 %
    ERROR    — AuthExpiredError (credentials expired)
    CRITICAL — all platforms unavailable / configuration corrupt

Usage::

    from webui_app.services.alerting import alert_registry

    # Create an alert
    alert_registry.add("medium-auth", "ERROR", "Medium 账号凭证已过期，请重新绑定")

    # Check active alerts
    active = alert_registry.active()

    # Resolve when fixed
    alert_registry.resolve("medium-auth")
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
import threading
from typing import Any


@dataclass
class Alert:
    """A single active alert with severity level and context."""

    id: str
    level: str  # INFO | WARN | ERROR | CRITICAL
    message: str
    created_at: str = ""
    resolved_at: str | None = None
    suggestion: str = ""  # operator-facing remediation hint

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "level": self.level,
            "message": self.message,
            "created_at": self.created_at or "",
            "resolved_at": self.resolved_at,
            "suggestion": self.suggestion,
            "active": self.resolved_at is None,
        }


# Severity order for display sorting
_SEVERITY_ORDER = {"CRITICAL": 0, "ERROR": 1, "WARN": 2, "INFO": 3}

# Remediation suggestions per alert pattern
_SUGGESTIONS: dict[str, str] = {
    "auth_expired": "前往 /settings 重新绑定平台凭证",
    "survival_low": "检查平台内容政策是否变更，考虑暂停该平台发布",
    "rate_limited": "降低发布频率或增加平台间延迟",
    "all_platforms_down": "检查网络连接和 config 配置",
    "config_corrupt": "检查 config.toml 和 JSON 状态文件完整性",
}


class AlertRegistry:
    """Thread-safe in-memory alert registry.

    Alerts are ephemeral (lost on restart). For persistent alerts, combine
    with a store or reconstruct from health-check data on startup.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._alerts: dict[str, Alert] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        alert_id: str,
        level: str,
        message: str,
        suggestion: str = "",
    ) -> Alert:
        """Create or update an alert. If *alert_id* already exists and is
        active, its level and message are updated (no duplicate)."""
        now = datetime.now(UTC).isoformat()
        if not suggestion:
            # Try to find a matching suggestion by prefix
            for key, hint in _SUGGESTIONS.items():
                if key in alert_id or key in message.lower():
                    suggestion = hint
                    break

        with self._lock:
            existing = self._alerts.get(alert_id)
            if existing and existing.resolved_at is None:
                existing.level = level
                existing.message = message
                existing.suggestion = suggestion or existing.suggestion
                return existing

            alert = Alert(
                id=alert_id,
                level=level,
                message=message,
                created_at=now,
                suggestion=suggestion,
            )
            self._alerts[alert_id] = alert
            return alert

    def resolve(self, alert_id: str) -> bool:
        """Mark an alert as resolved. Returns True if the alert existed."""
        now = datetime.now(UTC).isoformat()
        with self._lock:
            alert = self._alerts.get(alert_id)
            if alert:
                alert.resolved_at = now
                return True
            return False

    def resolve_by_prefix(self, prefix: str) -> int:
        """Resolve all alerts whose ID starts with *prefix*.

        Returns the count of resolved alerts.
        """
        now = datetime.now(UTC).isoformat()
        count = 0
        with self._lock:
            for alert in self._alerts.values():
                if alert.resolved_at is None and alert.id.startswith(prefix):
                    alert.resolved_at = now
                    count += 1
        return count

    def active(self) -> list[Alert]:
        """Return currently active alerts, sorted by severity (CRITICAL first)."""
        with self._lock:
            result = [
                a for a in self._alerts.values() if a.resolved_at is None
            ]
        result.sort(key=lambda a: (_SEVERITY_ORDER.get(a.level, 9), a.created_at))
        return result

    def all(self) -> list[Alert]:
        """Return all alerts (active + resolved), newest severity-first."""
        with self._lock:
            result = list(self._alerts.values())
        result.sort(key=lambda a: (_SEVERITY_ORDER.get(a.level, 9), a.created_at or ""))
        return result

    def clear_resolved(self) -> int:
        """Remove all resolved alerts from the registry. Returns count."""
        count = 0
        with self._lock:
            keys = [k for k, a in self._alerts.items() if a.resolved_at is not None]
            for k in keys:
                del self._alerts[k]
                count += 1
        return count

    def to_dicts(self, only_active: bool = True) -> list[dict[str, Any]]:
        """Return alerts as dicts (for JSON API serialization)."""
        source = self.active() if only_active else self.all()
        return [a.to_dict() for a in source]


# Module-level singleton
alert_registry = AlertRegistry()
