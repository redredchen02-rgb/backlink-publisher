"""Unit tests for webui_app.services.alerting (Plan 2026-06-10-002 U4.3)."""


from __future__ import annotations
__tier__ = "unit"

from webui_app.services.alerting import AlertRegistry


class TestAlertRegistry:
    def test_add_and_active(self):
        ar = AlertRegistry()
        ar.add("test-1", "WARN", "test warning")
        active = ar.active()
        assert len(active) == 1
        assert active[0].id == "test-1"
        assert active[0].level == "WARN"
        assert active[0].resolved_at is None

    def test_add_duplicate_updates_level(self):
        ar = AlertRegistry()
        ar.add("dup", "WARN", "first")
        ar.add("dup", "ERROR", "updated")
        active = ar.active()
        assert len(active) == 1
        assert active[0].level == "ERROR"
        assert active[0].message == "updated"

    def test_add_duplicate_resolved_creates_new(self):
        ar = AlertRegistry()
        ar.add("dup", "WARN", "first")
        ar.resolve("dup")
        ar.add("dup", "ERROR", "new instance after resolve")
        active = ar.active()
        assert len(active) == 1
        assert active[0].message == "new instance after resolve"

    def test_resolve(self):
        ar = AlertRegistry()
        ar.add("r", "ERROR", "to resolve")
        assert ar.resolve("r") is True
        assert len(ar.active()) == 0

    def test_resolve_nonexistent_returns_false(self):
        ar = AlertRegistry()
        assert ar.resolve("nonexistent") is False

    def test_resolve_by_prefix(self):
        ar = AlertRegistry()
        ar.add("auth-medium", "ERROR", "medium expired")
        ar.add("auth-blogger", "ERROR", "blogger expired")
        ar.add("survival", "WARN", "low survival")
        assert ar.resolve_by_prefix("auth") == 2
        assert len(ar.active()) == 1
        assert ar.active()[0].id == "survival"

    def test_resolve_by_prefix_no_match(self):
        ar = AlertRegistry()
        ar.add("x", "INFO", "some info")
        assert ar.resolve_by_prefix("z") == 0
        assert len(ar.active()) == 1

    def test_severity_sort(self):
        ar = AlertRegistry()
        ar.add("a1", "INFO", "info msg")
        ar.add("c1", "CRITICAL", "critical msg")
        ar.add("e1", "ERROR", "error msg")
        ar.add("w1", "WARN", "warn msg")
        sorted_alerts = ar.active()
        levels = [a.level for a in sorted_alerts]
        assert levels == ["CRITICAL", "ERROR", "WARN", "INFO"]

    def test_all_includes_resolved(self):
        ar = AlertRegistry()
        ar.add("a", "WARN", "active")
        ar.add("b", "ERROR", "resolved later")
        ar.resolve("b")
        all_alerts = ar.all()
        assert len(all_alerts) == 2

    def test_clear_resolved(self):
        ar = AlertRegistry()
        ar.add("x", "WARN", "will resolve")
        ar.add("y", "INFO", "stays active")
        ar.resolve("x")
        assert ar.clear_resolved() == 1
        assert len(ar.active()) == 1
        assert ar.active()[0].id == "y"

    def test_to_dicts_only_active(self):
        ar = AlertRegistry()
        ar.add("a", "ERROR", "err")
        ar.add("b", "INFO", "info")
        ar.resolve("b")
        dicts = ar.to_dicts(only_active=True)
        assert len(dicts) == 1
        assert dicts[0]["id"] == "a"
        assert dicts[0]["active"] is True

    def test_to_dicts_all(self):
        ar = AlertRegistry()
        ar.add("a", "ERROR", "err")
        ar.resolve("a")
        dicts = ar.to_dicts(only_active=False)
        assert len(dicts) == 1
        assert dicts[0]["active"] is False
        assert dicts[0]["resolved_at"] is not None

    def test_suggestion_auto_match(self):
        ar = AlertRegistry()
        ar.add("auth_expired", "ERROR", "Medium auth expired")
        active = ar.active()
        assert "重新绑定" in active[0].suggestion

    def test_empty_registry(self):
        ar = AlertRegistry()
        assert ar.active() == []
        assert ar.all() == []
        assert ar.to_dicts() == []
        assert ar.clear_resolved() == 0
