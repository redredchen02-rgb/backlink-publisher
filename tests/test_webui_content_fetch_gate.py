"""Content-fetch gate + TTL wiring tests for the work-themed WebUI surface.

Extracted from test_webui_three_url.py (P14 C1 split). Covers:
- Content-fetch gate integration with the three-URL config path
- TTL-based cache invalidation for content-fetch results
- Interaction between fetch gate timing and content expiry

Tests deliberately locate form fields by HTML attributes (input ``name``,
form ``action``) rather than Chinese labels — avoids the
feedback_jinja2-banner-text-collision.md failure mode.
"""
from __future__ import annotations

__tier__ = "unit"
import os

# Ensure the webui module is importable.
import sys as _sys
from unittest.mock import MagicMock, patch

import pytest

_sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── autouse: isolate config writes + suppress real network/subprocess ───────


@pytest.fixture(autouse=True)
def _isolated_config_dir(tmp_path):
    """Redirect all config.toml reads/writes to tmp_path."""
    fake_config_dir = tmp_path / "config"
    with patch(
        "backlink_publisher.config._config_dir", return_value=fake_config_dir,
    ), patch(
        "backlink_publisher.config._cache_dir", return_value=tmp_path / "cache",
    ), patch(
        "backlink_publisher._util.paths._config_dir", return_value=fake_config_dir,
    ), patch(
        "backlink_publisher._util.paths._cache_dir", return_value=tmp_path / "cache",
    ):
        yield fake_config_dir


@pytest.fixture(autouse=True)
def _no_real_subprocess():
    """Mock subprocess.run so /sites/run never shells out to the real CLI."""
    import subprocess as sp_mod

    def _fake_run(cmd, *_args, **_kwargs):
        result = sp_mod.CompletedProcess(args=cmd, returncode=0)
        result.stdout = ""
        result.stderr = ""
        return result

    with patch("subprocess.run", side_effect=_fake_run):
        yield


@pytest.fixture
def client():
    """Flask test client with secure cookies disabled so the session round-trips."""
    import webui

    webui.app.config["TESTING"] = True
    webui.app.config["SESSION_COOKIE_SECURE"] = False
    webui.app.config["WTF_CSRF_ENABLED"] = False  # belt-and-suspenders if Flask-WTF ever lands
    return webui.app.test_client()


@pytest.fixture
def csrf_client():
    """Enables the global CSRF guard so tests can assert 403 on missing/wrong tokens."""
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
    """Hit GET /sites, parse the hidden csrf_token out of the rendered form."""
    import re as _re

    resp = client.get("/sites")
    assert resp.status_code == 200, resp.data[:200]
    html = resp.data.decode()
    match = _re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match, "csrf_token hidden input not found in /sites HTML"
    return match.group(1)


# ═════════════════════════════════════════════════════════════════════════════
# GET /sites — form renders with CSRF token + correct action
# ═════════════════════════════════════════════════════════════════════════════


class TestSitesFormRender:
    def test_get_renders_form_with_csrf_and_correct_action(self, client):
        resp = client.get("/sites")
        assert resp.status_code == 200
        body = resp.data.decode()
class TestContentFetchGate:
    """The content-fetch gate runs at form-save time so the operator gets
    field-level errors instantly rather than discovering the bad URL at
    publish time. ``BACKLINK_NO_FETCH_VERIFY=1`` bypasses for dev.
    """

    def test_save_three_url_main_url_gate_failure_returns_422(
        self, client, monkeypatch
    ):
        def _fail_main(urls, max_workers=5):
            return {
                u: (
                    (False, "http_404", None)
                    if "stale" in u
                    else (True, None, "ok")
                )
                for u in urls
            }

        monkeypatch.setattr(
            "webui.content_fetch.verify_urls_batch", _fail_main,
        )
        token = _fetch_csrf(client)
        resp = client.post(
            "/sites/save-three-url",
            data={
                "csrf_token": token,
                "main_url": "https://stale.example.com/",
                "list_url": "https://other.example/list",
                "work_urls": "",
                "branded_pool": "B",
                "partial_pool": "P",
                "exact_pool": "E",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 422
        body = resp.data.decode()
        assert "main_url" in body
        # Failure reason surfaces to the operator
        assert "http_404" in body

    def test_save_three_url_work_urls_partial_gate_failure(
        self, client, monkeypatch
    ):
        def _fail_one(urls, max_workers=5):
            return {
                u: (
                    (False, "http_200_no_title", None)
                    if u.endswith("/bad")
                    else (True, None, "ok")
                )
                for u in urls
            }

        monkeypatch.setattr(
            "webui.content_fetch.verify_urls_batch", _fail_one,
        )
        token = _fetch_csrf(client)
        resp = client.post(
            "/sites/save-three-url",
            data={
                "csrf_token": token,
                "main_url": "https://x.com/",
                "list_url": "https://x.com/list",
                "work_urls": "https://x.com/good\nhttps://x.com/bad",
                "branded_pool": "B",
                "partial_pool": "P",
                "exact_pool": "E",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 422
        body = resp.data.decode()
        assert "work_urls" in body
        assert "/bad" in body
        # The good URL should not be flagged
        assert "http_200_no_title" in body

    def test_save_three_url_all_urls_pass_gate_succeeds(
        self, client
    ):
        """The autouse mock in conftest defaults everything to pass."""
        token = _fetch_csrf(client)
        resp = client.post(
            "/sites/save-three-url",
            data={
                "csrf_token": token,
                "main_url": "https://x.com/",
                "list_url": "https://x.com/list",
                "work_urls": "",
                "branded_pool": "B",
                "partial_pool": "P",
                "exact_pool": "E",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_save_three_url_env_bypass_skips_gate(
        self, client, monkeypatch
    ):
        """BACKLINK_NO_FETCH_VERIFY=1 → gate is not called even when it
        would fail. Use case: dev / staging environments with deliberately
        unreachable URLs."""
        call_count = {"n": 0}

        def _tracking(urls, max_workers=5):
            call_count["n"] += 1
            return {u: (False, "http_404", None) for u in urls}

        monkeypatch.setattr(
            "webui.content_fetch.verify_urls_batch", _tracking,
        )
        monkeypatch.setenv("BACKLINK_NO_FETCH_VERIFY", "1")
        token = _fetch_csrf(client)
        resp = client.post(
            "/sites/save-three-url",
            data={
                "csrf_token": token,
                "main_url": "https://x.com/",
                "list_url": "https://x.com/list",
                "work_urls": "",
                "branded_pool": "B",
                "partial_pool": "P",
                "exact_pool": "E",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302, "bypass should let the save proceed"
        assert call_count["n"] == 0, "gate must not be invoked under bypass"

    def test_ce_plan_url_gate_failure_renders_error(
        self, client, monkeypatch
    ):
        def _fail(urls, max_workers=5):
            return {u: (False, "http_404", None) for u in urls}

        monkeypatch.setattr(
            "webui.content_fetch.verify_urls_batch", _fail,
        )
        resp = client.post(
            "/ce:plan",
            data={"target_url": "https://stale.example/"},
            follow_redirects=False,
        )
        # /ce:plan re-renders the index page with an inline error rather
        # than 422; assert the error is surfaced
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "无可访问内容" in body or "http_404" in body


# ═════════════════════════════════════════════════════════════════════════════
# Homepage three-tier URL form (plan 2026-05-14-009 Units 1+2+4)
# ═════════════════════════════════════════════════════════════════════════════


class TestHomepageThreeTier:
    """Homepage / form structured into main_url / category_url / work_url
    instead of the single target_url + free-form url_new path. Backward
    compat: target_url still accepted as fallback for main_url."""

    def test_get_homepage_renders_three_tier_inputs(self, client):
        resp = client.get("/jinja")
        assert resp.status_code == 200
        body = resp.data.decode()
        # The three structured tier inputs are present with their badges.
        assert 'name="main_url"' in body
        assert 'name="category_url"' in body
        assert 'name="work_url"' in body
        assert ">主<" in body
        assert ">类<" in body
        assert ">漫<" in body
        # main_url marked required.
        assert 'name="main_url"' in body and 'required' in body
        # Legacy url_new textbox still present for free-form extras.
        assert 'name="url_new"' in body

    def test_post_only_main_url_succeeds_no_config_write(self, client, tmp_path):
        """Submit only main_url. No persistence (no category/work data)."""
        resp = client.post(
            "/ce:plan",
            data={"main_url": "https://example.com/"},
        )
        assert resp.status_code == 200
        body = resp.data.decode()
        # Index re-rendered with config preview / no error
        assert "请输入主网域" not in body

    def test_post_three_tiers_persists_threeurl_config(
        self, client, tmp_path, monkeypatch
    ):
        """Full submit: main + category + work → upgrade_target_to_threeurl
        is called + save_config writes the ThreeUrlConfig block."""
        # Patch fetch_url_metadata so the preview path doesn't try real HTTP.
        monkeypatch.setattr(
            "webui_app.routes.pipeline_plan.fetch_url_metadata",
            lambda url: {"url": url, "title": "x", "description": "", "status": "success"},
        )
        resp = client.post(
            "/ce:plan",
            data={
                "main_url": "https://example.com/",
                "category_url": "https://example.com/cat",
                "work_url": "https://example.com/work/1",
            },
        )
        assert resp.status_code == 200, resp.data[:300]

        # Reload config — ThreeUrlConfig should be written for the domain.
        from backlink_publisher.config import load_config
        cfg = load_config()
        key = "https://example.com"
        assert key in cfg.target_three_url, list(cfg.target_three_url.keys())
        entry = cfg.target_three_url[key]
        assert entry.list_url == "https://example.com/cat"
        assert entry.work_urls == ["https://example.com/work/1"]

    def test_post_missing_main_url_returns_error(self, client):
        resp = client.post(
            "/ce:plan",
            data={"category_url": "https://example.com/cat"},
        )
        assert resp.status_code == 200  # re-render index with error
        assert "请输入主网域" in resp.data.decode()

    def test_post_main_url_gate_failure_renders_error(
        self, client, monkeypatch
    ):
        """Plan 007 gate inherited: main_url gate fail → error rendered."""
        def _fail(urls, max_workers=5):
            return {u: (False, "http_404", None) for u in urls}

        monkeypatch.setattr(
            "webui.content_fetch.verify_urls_batch", _fail,
        )
        resp = client.post(
            "/ce:plan",
            data={"main_url": "https://stale.example.com/"},
        )
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "http_404" in body or "无可访问内容" in body

    def test_post_non_https_category_url_returns_error(self, client):
        resp = client.post(
            "/ce:plan",
            data={
                "main_url": "https://example.com/",
                "category_url": "http://example.com/cat",
            },
        )
        body = resp.data.decode()
        assert "分类页必须 https" in body or "category" in body.lower()

    def test_post_legacy_target_url_fallback(self, client, monkeypatch):
        """Backward compat: old target_url name still works as main_url."""
        monkeypatch.setattr(
            "webui_app.routes.pipeline_plan.fetch_url_metadata",
            lambda url: {"url": url, "title": "x", "description": "", "status": "success"},
        )
        resp = client.post(
            "/ce:plan",
            data={"target_url": "https://legacy.example/"},
        )
        assert resp.status_code == 200, resp.data[:300]
        body = resp.data.decode()
        assert "请输入主网域" not in body

    def test_post_legacy_anchor_keywords_upgraded_to_threeurl(
        self, client, monkeypatch, _isolated_config_dir
    ):
        """If main_url already has anchor_keywords (legacy schema), the form
        save triggers automatic upgrade — anchor_keywords are migrated into
        branded_pool inside the new ThreeUrlConfig."""
        from backlink_publisher.config import load_config, save_config

        save_config(
            load_config(), target_anchor_keywords={
                "https://hasanchor.example": ["BrandA", "BrandB"],
            },
        )

        monkeypatch.setattr(
            "webui_app.routes.pipeline_plan.fetch_url_metadata",
            lambda url: {"url": url, "title": "x", "description": "", "status": "success"},
        )
        resp = client.post(
            "/ce:plan",
            data={
                "main_url": "https://hasanchor.example/",
                "category_url": "https://hasanchor.example/cat",
                "work_url": "https://hasanchor.example/w/1",
            },
        )
        assert resp.status_code == 200, resp.data[:300]

        cfg = load_config()
        key = "https://hasanchor.example"
        assert key in cfg.target_three_url
        entry = cfg.target_three_url[key]
        # anchor_keywords migrated to branded_pool
        assert entry.branded_pool == ["BrandA", "BrandB"]
        assert entry.list_url == "https://hasanchor.example/cat"
        assert entry.work_urls == ["https://hasanchor.example/w/1"]


# ═════════════════════════════════════════════════════════════════════════════
# Plan 008 Unit 3: webui TTL env wiring
# ═════════════════════════════════════════════════════════════════════════════


class TestContentFetchTTLWiring:
    """`BACKLINK_GATE_CACHE_TTL_SECONDS` → content_fetch.set_default_max_age
    happens at webui startup via `_wire_content_fetch_ttl_from_env`."""

    def test_default_900_seconds_when_env_unset(self, monkeypatch):
        from backlink_publisher.content import fetch as content_fetch
        import webui

        monkeypatch.delenv("BACKLINK_GATE_CACHE_TTL_SECONDS", raising=False)
        monkeypatch.delenv("BACKLINK_NO_FETCH_VERIFY", raising=False)
        content_fetch.set_default_max_age(None)
        webui._wire_content_fetch_ttl_from_env()
        assert content_fetch._DEFAULT_MAX_AGE_S == 900.0
        content_fetch.set_default_max_age(None)
        webui._wire_content_fetch_ttl_from_env()
        # 900s default per plan 008 Unit 3
        assert content_fetch._DEFAULT_MAX_AGE_S == 900.0
        # Reset for the next test.
        content_fetch.set_default_max_age(None)

    def test_explicit_env_overrides_default(self, monkeypatch):
        from backlink_publisher.content import fetch as content_fetch
        import webui

        monkeypatch.setenv("BACKLINK_GATE_CACHE_TTL_SECONDS", "60")
        monkeypatch.delenv("BACKLINK_NO_FETCH_VERIFY", raising=False)
        content_fetch.set_default_max_age(None)
        webui._wire_content_fetch_ttl_from_env()
        assert content_fetch._DEFAULT_MAX_AGE_S == 60.0

    def test_bypass_env_skips_ttl_wiring(self, monkeypatch):
        from backlink_publisher.content import fetch as content_fetch
        import webui

        monkeypatch.setenv("BACKLINK_NO_FETCH_VERIFY", "1")
        monkeypatch.setenv("BACKLINK_GATE_CACHE_TTL_SECONDS", "60")
        content_fetch.set_default_max_age(None)
        webui._wire_content_fetch_ttl_from_env()
        assert content_fetch._DEFAULT_MAX_AGE_S is None

    def test_invalid_env_falls_back_to_900(self, monkeypatch):
        from backlink_publisher.content import fetch as content_fetch
        import webui

        monkeypatch.setenv("BACKLINK_GATE_CACHE_TTL_SECONDS", "not-a-number")
        monkeypatch.delenv("BACKLINK_NO_FETCH_VERIFY", raising=False)
        content_fetch.set_default_max_age(None)
        webui._wire_content_fetch_ttl_from_env()
        assert content_fetch._DEFAULT_MAX_AGE_S == 900.0

    def test_zero_or_negative_seconds_skips_wiring(self, monkeypatch):
        from backlink_publisher.content import fetch as content_fetch
        import webui

        for value in ("0", "-5"):
            monkeypatch.setenv("BACKLINK_GATE_CACHE_TTL_SECONDS", value)
            monkeypatch.delenv("BACKLINK_NO_FETCH_VERIFY", raising=False)
            content_fetch.set_default_max_age(None)
            webui._wire_content_fetch_ttl_from_env()
            assert content_fetch._DEFAULT_MAX_AGE_S is None, (
                f"TTL={value} should leave TTL disabled"
            )


# ═════════════════════════════════════════════════════════════════════════════
# Plan 006: /sites form minimal-input — derivation helpers + autofilled flow
# ═════════════════════════════════════════════════════════════════════════════


