"""Plan 2026-05-26-002 Unit 3 — auth-type-aware channel status.

DOM rendering tests removed in U8 (Plan 2026-06-18-002) — the legacy /settings
Jinja page was retired; SPA settings at /app/settings replaces it.

get_channel_status auth_type contract test is kept (pure logic, no HTTP).
"""
from __future__ import annotations

__tier__ = "unit"

from backlink_publisher.config import Config
from webui_app.binding_status import get_channel_status


def test_get_channel_status_includes_auth_type():
    cfg = Config()
    assert get_channel_status("txtfyi", cfg)["auth_type"] == "anon"
    assert get_channel_status("substack", cfg)["auth_type"] == "paste_blob"
    assert get_channel_status("blogger", cfg)["auth_type"] == "oauth"
