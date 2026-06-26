"""Contract for ``GET /api/v1/settings/channels`` — the channel binding-status
overview the SPA settings page's channel section hydrates from.

Plan 2026-06-18-002 U7 (Settings, section 3). Read-only single source over
``ChannelOverviewAPI`` (registry − hidden_from_ui ∘ get_channel_status); the
per-channel credential WRITES are covered elsewhere. This guards the read shape +
that no secret leaks into the list.
"""

from __future__ import annotations

__tier__ = "integration"

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))
    from webui_app import create_app
    a = create_app(start_scheduler=False)
    a.config["TESTING"] = True
    a.config["PROPAGATE_EXCEPTIONS"] = False
    a.config["SESSION_COOKIE_SECURE"] = False
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def test_list_channels_returns_status_rows(client):
    resp = client.get("/api/v1/settings/channels")
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    assert isinstance(body.get("channels"), list)
    assert body["channels"], "expected at least one registered, non-hidden channel"
    row = body["channels"][0]
    # the row carries what a status card needs
    for key in ("slug", "display_name", "auth_type", "bound", "blockers"):
        assert key in row, f"missing {key} in {row}"
    assert isinstance(row["bound"], bool)


def test_list_channels_excludes_hidden(client):
    """Every returned slug is registered and NOT hidden_from_ui."""
    from backlink_publisher.publishing.registry import registered_platforms
    from webui_app.binding_status import hidden_from_ui

    body = client.get("/api/v1/settings/channels").get_json()
    slugs = {c["slug"] for c in body["channels"]}
    registered = set(registered_platforms())
    hidden = set(hidden_from_ui())
    assert slugs <= registered
    assert not (slugs & hidden), "a hidden channel leaked into the overview"


def test_list_channels_leaks_no_credentials(client, tmp_path):
    """A channel row carries only status — never a token/api_key/secret FIELD.

    (We assert on row keys, not a substring scan: a ``blockers`` diagnostic may
    legitimately mention the word "api_key", e.g. "auth_failed: api_key rejected".)
    """
    body = client.get("/api/v1/settings/channels").get_json()
    for row in body["channels"]:
        for forbidden in ("token", "api_key", "secret", "password", "cookie"):
            assert forbidden not in row, f"{row['slug']} row leaked a {forbidden} field"
