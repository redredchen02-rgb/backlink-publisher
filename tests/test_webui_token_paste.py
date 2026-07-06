"""WebUI token-paste binding route + registry-driven card helper.

Unit 4b (Plan 2026-05-25-002): ``_token_paste_channels_from_registry``
derives token-paste status from ``bind_descriptors()`` so new platforms
only need a ``BindDescriptor(backend="token-paste")`` in ``register()``
to auto-appear — no manual 5-wire changes.
"""
from __future__ import annotations

__tier__ = "unit"
import json
import os
import stat
from typing import Any
from unittest import mock

import pytest

# Module-level import to register the route blueprint
from webui_app import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _csrf(client):
    """Grab a CSRF token by GET-ing the index; the session middleware
    seeds it into the meta tag."""
    resp = client.get("/jinja")
    assert resp.status_code == 200
    # Extract from <meta name="csrf-token" content="...">
    import re
    m = re.search(rb'name="csrf-token" content="([^"]+)"', resp.data)
    assert m, "no csrf token in index page"
    return m.group(1).decode()


# TestSaveTokenAllowlist, TestSaveGhpagesToken, TestClearToken, TestSaveDevtoToken,
# TestSaveNotionToken removed — /settings/save-channel-token + /settings/save-notion-token
# routes retired in U8 5b (Plan 2026-06-18-002). Coverage in test_webui_api_v1_*.py.


# ── Unit 4b: registry-driven token-paste helper ──────────────────────────────


@pytest.fixture(autouse=False)
def _registry_snapshot():
    from backlink_publisher.publishing.registry import (
        _BIND_BY_PLATFORM,
        _POLICY_BY_PLATFORM,
        _REGISTRY,
        _UI_META_BY_PLATFORM,
        _VISIBILITY_BY_PLATFORM,
    )

    snaps = [
        (_REGISTRY, dict(_REGISTRY)),
        (_UI_META_BY_PLATFORM, dict(_UI_META_BY_PLATFORM)),
        (_BIND_BY_PLATFORM, dict(_BIND_BY_PLATFORM)),
        (_POLICY_BY_PLATFORM, dict(_POLICY_BY_PLATFORM)),
        (_VISIBILITY_BY_PLATFORM, dict(_VISIBILITY_BY_PLATFORM)),
    ]
    try:
        yield
    finally:
        for store, snap in snaps:
            store.clear()
            store.update(snap)


class _FakePub:
    """Minimal publisher stub for registry isolation tests."""
    def publish(self, *a, **kw):  # pragma: no cover
        raise NotImplementedError

    def available(self) -> bool:  # pragma: no cover
        return True


class TestTokenPasteChannelsFromRegistry:
    """_token_paste_channels_from_registry() auto-discovers token-paste platforms."""

    def _mock_cfg(self, tmp_path):
        cfg = mock.MagicMock()
        cfg.config_dir = tmp_path
        return cfg

    @pytest.mark.usefixtures("_registry_snapshot")
    def test_new_platform_appears_after_register(self, tmp_path) -> None:
        from backlink_publisher.publishing._manifest_types import BindDescriptor
        from backlink_publisher.publishing.registry import register

        register(
            "fakepaste",
            _FakePub,
            dofollow=True,
            bind=[BindDescriptor(
                backend="token-paste",
                storage_state_path="<config_dir>/fakepaste-token.json",
            )],
        )

        from webui_app.helpers.contexts import _token_paste_channels_from_registry

        result = _token_paste_channels_from_registry(self._mock_cfg(tmp_path))
        assert "fakepaste" in result

    @pytest.mark.usefixtures("_registry_snapshot")
    def test_unbound_when_token_file_absent(self, tmp_path) -> None:
        from backlink_publisher.publishing._manifest_types import BindDescriptor
        from backlink_publisher.publishing.registry import register

        register(
            "fakepaste2",
            _FakePub,
            dofollow=True,
            bind=[BindDescriptor(
                backend="token-paste",
                storage_state_path="<config_dir>/fakepaste2-token.json",
            )],
        )

        from webui_app.helpers.contexts import _token_paste_channels_from_registry

        result = _token_paste_channels_from_registry(self._mock_cfg(tmp_path))
        assert result["fakepaste2"]["bound"] is False
        assert result["fakepaste2"]["masked"] == ""

    @pytest.mark.usefixtures("_registry_snapshot")
    def test_bound_when_token_file_present(self, tmp_path) -> None:
        from backlink_publisher.publishing._manifest_types import BindDescriptor
        from backlink_publisher.publishing.registry import register

        token_file = tmp_path / "fakepaste3-token.json"
        token_file.write_text(json.dumps({"token": "abcdefghijk"}), encoding="utf-8")

        register(
            "fakepaste3",
            _FakePub,
            dofollow=True,
            bind=[BindDescriptor(
                backend="token-paste",
                storage_state_path="<config_dir>/fakepaste3-token.json",
            )],
        )

        from webui_app.helpers.contexts import _token_paste_channels_from_registry

        result = _token_paste_channels_from_registry(self._mock_cfg(tmp_path))
        assert result["fakepaste3"]["bound"] is True
        assert "abcdefghijk" not in result["fakepaste3"]["masked"]

    @pytest.mark.usefixtures("_registry_snapshot")
    def test_custom_token_field_from_extras(self, tmp_path) -> None:
        from backlink_publisher.publishing._manifest_types import BindDescriptor
        from backlink_publisher.publishing.registry import register

        token_file = tmp_path / "fakepaste4-token.json"
        token_file.write_text(json.dumps({"api_key": "myapikey123456"}), encoding="utf-8")

        register(
            "fakepaste4",
            _FakePub,
            dofollow=True,
            bind=[BindDescriptor(
                backend="token-paste",
                storage_state_path="<config_dir>/fakepaste4-token.json",
                extras={"token_field": "api_key"},
            )],
        )

        from webui_app.helpers.contexts import _token_paste_channels_from_registry

        result = _token_paste_channels_from_registry(self._mock_cfg(tmp_path))
        assert result["fakepaste4"]["bound"] is True

    @pytest.mark.usefixtures("_registry_snapshot")
    def test_cookie_backend_excluded(self, tmp_path) -> None:
        from backlink_publisher.publishing._manifest_types import BindDescriptor
        from backlink_publisher.publishing.registry import register

        register(
            "cookie_chan",
            _FakePub,
            dofollow=True,
            bind=[BindDescriptor(
                backend="cookie",
                storage_state_path="<config_dir>/cookie-chan.json",
            )],
        )

        from webui_app.helpers.contexts import _token_paste_channels_from_registry

        result = _token_paste_channels_from_registry(self._mock_cfg(tmp_path))
        assert "cookie_chan" not in result

    @pytest.mark.usefixtures("_registry_snapshot")
    def test_requires_database_id_excluded(self, tmp_path) -> None:
        """Notion-style two-field platforms excluded (handled by explicit wiring)."""
        from backlink_publisher.publishing._manifest_types import BindDescriptor
        from backlink_publisher.publishing.registry import register

        register(
            "two_field",
            _FakePub,
            dofollow=True,
            bind=[BindDescriptor(
                backend="token-paste",
                storage_state_path="<config_dir>/two-field.json",
                extras={"requires_database_id": "true"},
            )],
        )

        from webui_app.helpers.contexts import _token_paste_channels_from_registry

        result = _token_paste_channels_from_registry(self._mock_cfg(tmp_path))
        assert "two_field" not in result

    def test_production_hackmd_included(self, tmp_path) -> None:
        import backlink_publisher.publishing.adapters  # noqa: F401
        from webui_app.helpers.contexts import _token_paste_channels_from_registry

        result = _token_paste_channels_from_registry(self._mock_cfg(tmp_path))
        assert "hackmd" in result

    def test_production_velog_excluded(self, tmp_path) -> None:
        """Velog uses backend=cookie — must NOT appear in token-paste cards."""
        import backlink_publisher.publishing.adapters  # noqa: F401
        from webui_app.helpers.contexts import _token_paste_channels_from_registry

        result = _token_paste_channels_from_registry(self._mock_cfg(tmp_path))
        assert "velog" not in result

    def test_production_notion_excluded(self, tmp_path) -> None:
        """Notion has requires_database_id — excluded from generic registry path."""
        import backlink_publisher.publishing.adapters  # noqa: F401
        from webui_app.helpers.contexts import _token_paste_channels_from_registry

        result = _token_paste_channels_from_registry(self._mock_cfg(tmp_path))
        assert "notion" not in result
