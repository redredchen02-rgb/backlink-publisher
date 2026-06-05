"""Unit 5 — Settings dashboard rendering (Plan 2026-05-19-006).

Verifies /settings GET renders the new "渠道綁定總覽" section with one
card per ``registered_platforms()`` entry, each carrying the
``data-channel`` attribute the Unit 5 JS binds against.

Companion: tests/test_generic_channel_api.py (Unit 4 — the API endpoints
the dashboard JS calls).
"""
from __future__ import annotations

__tier__ = "unit"
import re

import pytest

from backlink_publisher.publishing.registry import active_platforms
from webui_app import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


class TestDashboardSection:
    """The dashboard section appears at the top of /settings."""

    def test_settings_page_renders_200(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200

    def test_dashboard_section_heading_present(self, client):
        resp = client.get("/settings")
        body = resp.get_data(as_text=True)
        assert "渠道綁定總覽" in body

    def test_javascript_loaded(self, client):
        resp = client.get("/settings")
        body = resp.get_data(as_text=True)
        assert "/static/js/channel-binding.js" in body

    def test_csrf_meta_present(self, client):
        """JS reads csrf_token from <meta name="csrf-token"> — must exist."""
        resp = client.get("/settings")
        body = resp.get_data(as_text=True)
        assert re.search(r'<meta\s+name="csrf-token"', body), body


class TestPerChannelCards:
    """Every registered platform must render one card with the data-channel
    attribute the JS uses for routing button clicks.
    """

    def _visible_channels(self):
        # The dashboard template iterates ``active_platforms()`` which
        # filters by manifest ``visibility`` (excludes experimental/hidden/retired).
        # Sync the test with the template rather than duplicating the filter.
        return list(active_platforms())

    def test_card_rendered_for_every_registered_channel(self, client):
        resp = client.get("/settings")
        body = resp.get_data(as_text=True)
        for channel in self._visible_channels():
            # data-channel="<name>" appears on the card div + each button.
            pattern = f'data-channel="{channel}"'
            assert pattern in body, (
                f"No dashboard card found for registered channel {channel!r}"
            )

    def test_each_card_has_verify_button(self, client):
        resp = client.get("/settings")
        body = resp.get_data(as_text=True)
        for channel in self._visible_channels():
            # Verify Token button per channel.
            assert re.search(
                rf'class="[^"]*dch-btn-verify[^"]*"[^>]*data-channel="{channel}"',
                body,
            ), f"No Verify button for {channel!r}"

    def test_bindable_channels_have_bind_button(self, client):
        from backlink_publisher.cli._bind.channels import CHANNELS
        resp = client.get("/settings")
        body = resp.get_data(as_text=True)
        from webui_app.binding_status import HIDDEN_FROM_UI
        bindable = CHANNELS - HIDDEN_FROM_UI
        for channel in sorted(bindable):
            assert re.search(
                rf'class="[^"]*dch-btn-bind[^"]*"[^>]*data-channel="{channel}"',
                body,
            ), f"No Bind button for bindable channel {channel!r}"

    def test_non_bindable_channels_have_no_bind_button(self, client):
        from backlink_publisher.cli._bind.channels import CHANNELS
        resp = client.get("/settings")
        body = resp.get_data(as_text=True)
        for channel in self._visible_channels():
            if channel not in CHANNELS:
                assert not re.search(
                    rf'class="[^"]*dch-btn-bind[^"]*"[^>]*data-channel="{channel}"',
                    body,
                ), f"Unexpected Bind button for non-bindable channel {channel!r}"

    def test_no_channel_has_dryrun_button(self, client):
        resp = client.get("/settings")
        body = resp.get_data(as_text=True)
        assert "dch-btn-dryrun" not in body, "Stale Dry-Run button found in dashboard"


class TestDofollowBadges:
    """Per-channel dofollow knowledge surfaces as a UI badge."""

    def test_telegraph_card_shows_dofollow_badge(self, client):
        """Telegraph is known dofollow per _DOFOLLOW_BY_CHANNEL."""
        resp = client.get("/settings")
        body = resp.get_data(as_text=True)
        # Look for the telegraph card area + dofollow good badge nearby.
        # Crude but reliable for a 200-line section.
        assert "telegraph" in body
        assert 'badge-dofollow good' in body, (
            "Expected at least one dofollow badge for a dofollow-confirmed channel"
        )

    def test_dofollow_legend_classes_in_css(self, client):
        """All three dofollow badge styles are defined in the extracted CSS file (Plan B2 Unit 1)."""
        from pathlib import Path
        # CSS extracted to static/css/settings.css by Plan B2 Unit 1
        css_src = (
            Path(__file__).resolve().parents[1]
            / "webui_app" / "static" / "css" / "settings.css"
        ).read_text(encoding="utf-8")
        for css_class in ("badge-dofollow.good", "badge-dofollow.weak", "badge-dofollow.unknown"):
            assert css_class in css_src, f"Missing CSS class {css_class} in settings.css"


class TestDashboardDriftWithRegistry:
    """Drift between registry and dashboard cards must not happen silently.

    Per solution lesson `invert-drift-check-when-invariant-becomes-dynamic`:
    enforce at test-time with lazy import, never module-top-level assert.
    """

    def test_dashboard_card_count_equals_registered_platform_count(self, client):
        # The dashboard template uses ``active_platforms()`` (visibility-filtered),
        # not ``registered_platforms()``.  Sync the expected count with
        # the actual rendering source.
        resp = client.get("/settings")
        body = resp.get_data(as_text=True)
        # Count of `dashboard-channel-card` outer divs.
        card_count = body.count('class="dashboard-channel-card"')
        expected = len(active_platforms())
        assert card_count == expected, (
            f"Dashboard cards ({card_count}) != active platforms "
            f"({expected}). Drift detected — investigate "
            f"_settings_context.dashboard_channels and the card macro."
        )


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


class TestPartitionDom:
    """Plan 2026-06-05-007 Unit 3 — the overview panel renders a flat main area
    (usable now) plus a folded extension area (never-connected), instead of
    automation-tier accordions.
    """

    def _overview(self, client):
        """Return the #overview-panel..#section-channels slice of /settings."""
        body = client.get("/settings").get_data(as_text=True)
        start = body.index('id="overview-panel"')
        end = body.index('id="section-channels"')
        return body[start:end]

    def test_extension_area_panel_renders(self, client):
        ov = self._overview(client)
        assert re.search(r'id="ext-area"\s+class="collapse', ov), "missing #ext-area panel"
        assert 'data-bs-target="#ext-area"' in ov, "missing extension collapse toggle"

    def test_extension_header_shows_label(self, client):
        ov = self._overview(client)
        assert '拓展區' in ov, "extension area header label missing"

    def test_cards_partition_active_platforms_exactly(self, client):
        """R13 (mandatory drift): every active platform renders exactly once
        across main + extension — no loss, no duplication. Cards stay in the DOM
        even when the extension area is collapsed.
        """
        ov = self._overview(client)
        carded = re.findall(
            r'<div class="dashboard-channel-card" data-channel="([^"]+)"', ov
        )
        assert len(carded) == len(set(carded)), "a channel rendered twice"
        assert set(carded) == set(active_platforms())

    def test_anon_channel_in_main_area_above_extension(self, client):
        """R1: telegraph (anon) is usable → renders in the main area, which sits
        above the extension panel.
        """
        ov = self._overview(client)
        ext_pos = ov.index('id="ext-area"')
        telegraph_pos = ov.index('data-channel="telegraph"')
        assert telegraph_pos < ext_pos, "anon telegraph must render in main, above #ext-area"

    def test_unbound_channel_in_extension_area(self, client, monkeypatch):
        """R3: a never-connected non-anon platform renders inside #ext-area."""
        from webui_app import binding_status

        real = binding_status.get_channel_status

        def _patched(name, config):
            st = real(name, config)
            if name == "notion":
                return {**st, "bound": False}
            return st

        monkeypatch.setattr(binding_status, "get_channel_status", _patched)
        ov = self._overview(client)
        ext = ov[ov.index('id="ext-area"'):]
        assert 'data-channel="notion"' in ext, "unbound notion must render inside extension"

    def test_expired_channel_stays_in_main_with_reconnect(self, client, monkeypatch):
        """R2: an expired browser channel stays in main with a 需重連 marker,
        not folded into the extension area.
        """
        from webui_app import binding_status
        from webui_store import channel_status

        real = binding_status.get_channel_status

        def _patched(name, config):
            st = real(name, config)
            if name == "medium":
                return {**st, "bound": False}
            return st

        monkeypatch.setattr(binding_status, "get_channel_status", _patched)
        monkeypatch.setattr(
            channel_status,
            "list_all",
            lambda: {"medium": {"status": "expired", "bound_at": None}},
        )
        ov = self._overview(client)
        main = ov[:ov.index('id="ext-area"')]
        assert 'data-channel="medium"' in main, "expired medium must stay in main area"
        assert '需重連' in main, "expired channel must show a reconnect marker"

    def test_badges_and_buttons_preserved(self, client):
        """R7: re-partitioning doesn't strip the per-card badges/action buttons."""
        ov = self._overview(client)
        assert 'dch-btn-verify' in ov
        assert 'badge-dofollow' in ov


class TestPartitionPersistenceContract:
    """Plan 2026-06-05-007 Unit 4 — DOM contract the collapse-persistence JS
    depends on, plus a check that the JS is actually wired to #ext-area.
    """

    def test_extension_has_collapse_toggle(self, client):
        body = client.get("/settings").get_data(as_text=True)
        assert re.search(
            r'data-bs-toggle="collapse"\s+data-bs-target="#ext-area"', body
        ), "missing collapse toggle for #ext-area"
        assert re.search(r'id="ext-area"\s+class="collapse', body)

    def test_extension_panel_nested_inside_overview_panel(self, client):
        """The persistence JS scopes to #overview-panel, so #ext-area must live
        inside it (not just exist).
        """
        body = client.get("/settings").get_data(as_text=True)
        overview = body[
            body.index('id="overview-panel"'):body.index('id="section-channels"')
        ]
        assert 'id="ext-area"' in overview, "#ext-area not nested in #overview-panel"

    def test_settings_js_persists_extension_collapse(self):
        from pathlib import Path

        js = (
            Path(__file__).resolve().parents[1]
            / "webui_app" / "static" / "js" / "settings.js"
        ).read_text(encoding="utf-8")
        assert "settings:collapse:" in js
        assert "ext-area" in js


class TestGracefulDegradation:
    """If status dispatch raises, /settings must still render (dashboard
    section omitted) — solution lesson: dashboard is summary, not load-bearing.
    """

    def test_settings_renders_when_dashboard_context_empty(self, client, monkeypatch):
        """Simulate context with empty dashboard list — page must still 200."""
        # We patch get_channel_status to raise; the helper try/except in
        # _settings_context already produces dashboard_channels=[] on failure.
        from webui_app import binding_status

        def _boom(name, config):
            raise RuntimeError("intentional test failure")

        monkeypatch.setattr(binding_status, "get_channel_status", _boom)
        resp = client.get("/settings")
        assert resp.status_code == 200
        # Dashboard heading should not appear when channels list is empty.
        body = resp.get_data(as_text=True)
        assert "渠道綁定總覽" not in body
