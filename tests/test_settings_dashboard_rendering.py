"""Settings dashboard context tests — Plan 2026-05-19-006 / 2026-06-05-007.

DOM rendering tests (TestDashboardSection, TestPerChannelCards, TestDofollowBadges,
TestDashboardDriftWithRegistry, TestPartitionDom, TestPartitionPersistenceContract,
TestGracefulDegradation) removed in U8 (Plan 2026-06-18-002) — the legacy
/settings Jinja page was retired; SPA settings at /app/settings replaces it.

TestChannelPartitionContext is kept because it tests _settings_context() directly
without serving the /settings route.
"""
from __future__ import annotations

__tier__ = "unit"

import pytest

from backlink_publisher.publishing.registry import active_platforms


class TestChannelPartitionContext:
    """Plan 2026-06-05-007 — _settings_context() exposes ``dashboard_partition``
    (main / extension area) whose members are exactly active_platforms().
    Replaces the old tier-grouping context tests.
    """

    def _partition(self):
        """Build the real settings context via an app/request context."""
        from webui_app import create_app
        from webui_app.helpers.contexts import _settings_context

        app = create_app()
        app.config["TESTING"] = True
        with app.test_request_context("/settings"):
            return _settings_context()["dashboard_partition"]

    @staticmethod
    def _members(partition):
        names = [n for n, _, _ in partition["main"]]
        names += [
            n for g in partition["extension_groups"] for n, _, _ in g["channels"]
        ]
        return names

    def test_partition_present_and_covers_active_platforms(self):
        partition = self._partition()
        assert partition is not None, "expected a partition dict"
        members = self._members(partition)
        # No channel appears in more than one area.
        assert len(members) == len(set(members)), "channel duplicated across areas"
        # Union == active_platforms() (no channel lost, none invented).
        assert set(members) == set(active_platforms())
        # Counts agree with the rendered lists.
        assert partition["main_count"] == len(partition["main"])

    def test_extension_tier_keys_are_ordered_subset(self):
        keys = [g["key"] for g in self._partition()["extension_groups"]]
        # Order preserved (tier-1 before tier-2 before tier-3), no duplicates.
        assert keys == sorted(set(keys), key=["tier-1", "tier-2", "tier-3"].index)

    def test_none_auth_type_channel_not_lost(self, monkeypatch):
        """R10 integration: a live channel with auth_type=None never vanishes —
        it lands in either area (here: extension, since unbound + non-anon).
        """
        from backlink_publisher.publishing import registry

        target = active_platforms()[0]
        real_auth_type = registry.auth_type

        def _fake_auth_type(name):
            return None if name == target else real_auth_type(name)

        monkeypatch.setattr(registry, "auth_type", _fake_auth_type)

        members = set(self._members(self._partition()))
        assert target in members, f"{target} vanished from both areas"

    def test_csdn_juejin_absent_from_all_areas(self):
        members = set(self._members(self._partition()))
        assert "csdn" not in members
        assert "juejin" not in members

    def test_partition_failure_falls_back_to_none(self, monkeypatch):
        """Error path: if partition_channels_by_connection raises, the key is
        None and _settings_context() does not propagate the error.
        """
        from webui_app.helpers import channel_tiers

        def _boom(*_args, **_kwargs):
            raise RuntimeError("intentional partition failure")

        monkeypatch.setattr(
            channel_tiers, "partition_channels_by_connection", _boom
        )

        from webui_app import create_app
        from webui_app.helpers.contexts import _settings_context

        app = create_app()
        app.config["TESTING"] = True
        with app.test_request_context("/settings"):
            ctx = _settings_context()
        assert ctx["dashboard_partition"] is None
