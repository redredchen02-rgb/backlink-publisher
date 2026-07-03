"""WebUI test fixtures — proof of concept for conftest.py split.

This conftest re-exports shared webui fixtures from the root conftest
so tests in this subdirectory can use them without import changes.

Future: move the actual fixture definitions here from root conftest.py
once all webui tests are migrated to this subdirectory.
"""

from __future__ import annotations

import re

import pytest


@pytest.fixture
def client():
    """Flask test client with TESTING + insecure cookies for session round-trip."""
    import webui

    webui.app.config["TESTING"] = True
    webui.app.config["SESSION_COOKIE_SECURE"] = False
    webui.app.config["WTF_CSRF_ENABLED"] = False
    return webui.app.test_client()


@pytest.fixture
def csrf_client():
    """Flask test client with the global CSRF guard enabled.

    Use for tests asserting that missing/wrong CSRF returns 403.
    """
    import webui

    webui.app.config["TESTING"] = True
    webui.app.config["SESSION_COOKIE_SECURE"] = False
    webui.app.config["WTF_CSRF_ENABLED"] = True
    webui.app.config["CSRF_ENABLED"] = True
    try:
        yield webui.app.test_client()
    finally:
        webui.app.config["WTF_CSRF_ENABLED"] = False
        webui.app.config["CSRF_ENABLED"] = False


def _fetch_csrf(client) -> str:
    """Grab the hidden csrf_token from GET /sites."""
    resp = client.get("/sites")
    assert resp.status_code == 200, resp.data[:200]
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', resp.data.decode())
    assert match, "csrf_token not found in /sites HTML"
    return match.group(1)
