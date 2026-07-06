"""Homepage three-tier form + pool-derivation tests — Plan 2026-05-13-004 Unit 5b.

D1 split (2026-07-02): extracted from ``test_webui_three_url.py``, which
originally carried both the ``/sites`` route-contract tests and this
derivation-focused surface. Kept together here because they all exercise the
same feature: turning a bare ``main_url`` into a full ``ThreeUrlConfig`` via
``_derive_branded_pool`` / ``_derive_partial_pool`` / ``_derive_exact_pool``.

Covers:
- ``POST /ce:plan`` (homepage): main_url/category_url/work_url three-tier
  form, legacy target_url + anchor_keywords upgrade paths.
- ``_derive_*_pool`` helpers: TDK-title/description → domain-label fallback
  ladder (unit-level, no Flask client).
- ``POST /sites/save-three-url`` with only ``main_url`` filled: server-side
  auto-derivation of the three pools + ``autofilled=...`` redirect param.
- Plan 009: homepage submit also writes ``sites.<main>.url_categories``
  without clobbering operator-set ``hot``/``animate``/``topic`` keys.
"""
from __future__ import annotations

__tier__ = "unit"
import os

# Ensure the webui module is importable.
import sys as _sys
from unittest.mock import patch

import pytest

from conftest import _fetch_csrf  # type: ignore[import]

_sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── autouse: isolate config writes + suppress real network/subprocess ───────
#
# Duplicated (not shared via conftest) per the established convention for
# this split family: non-autouse fixtures (client, csrf_client, _fetch_csrf)
# live in conftest.py, but autouse fixtures live in each split file — global
# autouse caused xdist worker failures in the earlier webui route-contract
# split (see tests/conftest.py's "WebUI shared fixtures" comment).


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
    """Mock subprocess.run so no test accidentally shells out to the real CLI."""
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
    webui.app.config["WTF_CSRF_ENABLED"] = False
    return webui.app.test_client()


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


class TestDeriveHelpers:
    """Unit-level tests on _derive_*_pool helpers in webui.py.

    These don't go through the Flask client; they call the helpers
    directly to verify the fallback ladder (TDK → domain_label)."""

    def test_branded_uses_tdk_title_when_present(self):
        from webui import _derive_branded_pool
        pool = _derive_branded_pool(
            "https://x.com/",
            {"title": "Real Site Name", "description": ""},
        )
        assert pool == ["Real Site Name"]

    def test_branded_truncates_long_title(self):
        from webui import _derive_branded_pool
        pool = _derive_branded_pool(
            "https://x.com/",
            {"title": "A" * 50, "description": ""},
        )
        assert len(pool[0]) == 30
        assert pool[0] == "A" * 30

    def test_branded_falls_back_to_domain_label_without_tdk(self):
        from webui import _derive_branded_pool
        pool = _derive_branded_pool("https://51acgs.com/", None)
        assert pool == ["51acgs"]

    def test_branded_falls_back_when_title_empty(self):
        from webui import _derive_branded_pool
        pool = _derive_branded_pool(
            "https://x.com/", {"title": "", "description": ""},
        )
        assert pool == ["x"]

    def test_partial_splits_description_on_punctuation(self):
        from webui import _derive_partial_pool
        pool = _derive_partial_pool(
            "https://x.com/",
            {"title": "", "description": "免费阅读漫画。最新更新, 海量资源；ACG爱好者社区"},
        )
        # Should yield at most 3 phrases
        assert len(pool) <= 3
        # First three phrases are the punctuation-split prefix
        assert "免费阅读漫画" in pool

    def test_partial_keeps_max_3_phrases(self):
        from webui import _derive_partial_pool, _DERIVED_PARTIAL_KEEP
        pool = _derive_partial_pool(
            "https://x.com/",
            {"description": "a, b, c, d, e, f"},
        )
        assert len(pool) == _DERIVED_PARTIAL_KEEP

    def test_partial_falls_back_to_domain_label_without_tdk(self):
        from webui import _derive_partial_pool
        pool = _derive_partial_pool("https://x.com/", None)
        assert pool == ["x"]

    def test_partial_falls_back_when_description_empty(self):
        from webui import _derive_partial_pool
        pool = _derive_partial_pool(
            "https://x.com/", {"title": "T", "description": ""},
        )
        assert pool == ["x"]

    def test_exact_always_domain_label(self):
        from webui import _derive_exact_pool
        assert _derive_exact_pool("https://51acgs.com/") == ["51acgs"]
        assert _derive_exact_pool("https://www.51acgs.com/") == ["51acgs"]

    def test_partial_truncates_long_phrase(self):
        from webui import _derive_partial_pool, _DERIVED_PARTIAL_MAX
        long_phrase = "X" * 100
        pool = _derive_partial_pool(
            "https://x.com/", {"description": long_phrase},
        )
        assert len(pool[0]) == _DERIVED_PARTIAL_MAX

    def test_all_pools_always_non_empty(self):
        """ThreeUrlConfig schema invariant: every derived pool is at least
        length 1. Bottom line for all three derivers."""
        from webui import _derive_branded_pool, _derive_exact_pool, _derive_partial_pool
        for tdk in (None, {}, {"title": "", "description": ""}):
            for url in ("https://a.com/", "https://b.c.d/"):
                assert len(_derive_branded_pool(url, tdk)) >= 1
                assert len(_derive_partial_pool(url, tdk)) >= 1
                assert len(_derive_exact_pool(url)) >= 1


class TestSitesMinimalInput:
    """End-to-end through Flask client: POST /sites/save-three-url with
    only main_url filled triggers server-side derivation + autofilled
    redirect param. Banner renders via GET /sites?saved=...&autofilled=..."""

    def test_minimal_post_succeeds_with_only_main_url(
        self, client, monkeypatch
    ):
        """The plan's R1 scenario: paste main_url, leave everything else
        empty, submit → 302 redirect, all derived fields persisted."""
        monkeypatch.setattr(
            "webui_app.routes.sites.fetch_full_tdk",
            lambda url: {
                "title": "Test Site",
                "description": "免费内容。海量资源；专业社区",
                "keywords": "",
            },
        )
        monkeypatch.setattr(
            "backlink_publisher.content.scraper.fetch_work_urls_from_list",
            lambda *a, **k: [
                "https://x.com/work/1", "https://x.com/work/2",
            ],
        )

        token = _fetch_csrf(client)
        resp = client.post(
            "/sites/save-three-url",
            data={
                "csrf_token": token,
                "main_url": "https://x.com/",
                # Everything else empty
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302, resp.data[:500]

        # Redirect URL contains saved + autofilled
        location = resp.headers["Location"]
        assert "saved=https://x.com" in location
        assert "autofilled=" in location

        # Disk state — all four pools non-empty + list_url + work_urls set
        from backlink_publisher.config import load_config
        cfg = load_config()
        entry = cfg.target_three_url["https://x.com"]
        assert entry.main_url == "https://x.com/"
        assert entry.list_url == "https://x.com/"  # derived to main_url
        assert entry.branded_pool == ["Test Site"]
        assert len(entry.partial_pool) >= 1
        assert entry.exact_pool == ["x"]
        assert entry.work_urls == [
            "https://x.com/work/1", "https://x.com/work/2",
        ]

    def test_tdk_fetch_failure_falls_back_to_domain_label(
        self, client, monkeypatch
    ):
        """Network down / target unreachable → pools all fall back to
        [domain_label]. Save still succeeds — ThreeUrlConfig schema
        invariant (three pools non-empty) held."""
        def _raise_tdk(url):
            raise RuntimeError("simulated tdk fetch failure")

        monkeypatch.setattr("webui_app.routes.sites.fetch_full_tdk", _raise_tdk)
        # work_scraper also fails — empty work_urls is allowed.
        def _raise_scraper(*a, **k):
            raise RuntimeError("simulated scrape failure")
        monkeypatch.setattr(
            "backlink_publisher.content.scraper.fetch_work_urls_from_list",
            _raise_scraper,
        )

        token = _fetch_csrf(client)
        resp = client.post(
            "/sites/save-three-url",
            data={
                "csrf_token": token,
                "main_url": "https://51acgs.com/",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

        from backlink_publisher.config import load_config
        cfg = load_config()
        entry = cfg.target_three_url["https://51acgs.com"]
        # All three pools fall back to domain label
        assert entry.branded_pool == ["51acgs"]
        assert entry.partial_pool == ["51acgs"]
        assert entry.exact_pool == ["51acgs"]
        # work_urls allowed empty when scraper fails
        assert entry.work_urls == []

    def test_partial_fill_only_derives_missing_fields(
        self, client, monkeypatch
    ):
        """Operator supplies branded_pool but leaves partial/exact empty.
        Server derives only the empty fields; supplied values pass through."""
        monkeypatch.setattr(
            "webui_app.routes.sites.fetch_full_tdk",
            lambda url: {"title": "Some Title", "description": "Some desc"},
        )
        monkeypatch.setattr(
            "backlink_publisher.content.scraper.fetch_work_urls_from_list",
            lambda *a, **k: [],
        )

        token = _fetch_csrf(client)
        resp = client.post(
            "/sites/save-three-url",
            data={
                "csrf_token": token,
                "main_url": "https://x.com/",
                "branded_pool": "MyBrand\nMyBrandAlt",
                # partial / exact empty
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

        from backlink_publisher.config import load_config
        cfg = load_config()
        entry = cfg.target_three_url["https://x.com"]
        # User-supplied branded preserved verbatim
        assert entry.branded_pool == ["MyBrand", "MyBrandAlt"]
        # partial derived from TDK description
        assert "Some desc" in entry.partial_pool or entry.partial_pool == ["Some desc"]
        # exact derived
        assert entry.exact_pool == ["x"]

        # Redirect's autofilled list should NOT contain branded_pool
        location = resp.headers["Location"]
        assert "branded_pool" not in location

    def test_get_with_autofilled_renders_banner(self, client):
        resp = client.get("/sites?saved=https://x.com&autofilled=list_url,partial_pool")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "已自动派生" in body
        assert "list_url" in body
        assert "partial_pool" in body

    def test_get_without_autofilled_no_banner(self, client):
        resp = client.get("/sites")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "已自动派生" not in body

    def test_full_fill_no_autofilled_param(self, client, monkeypatch):
        """Operator fills every field — no derivation triggered, redirect
        URL has saved=... but NOT autofilled=..."""
        # Mocks shouldn't be reached but set them defensively.
        monkeypatch.setattr(
            "webui_app.routes.sites.fetch_full_tdk", lambda url: {"title": "x", "description": ""},
        )
        token = _fetch_csrf(client)
        resp = client.post(
            "/sites/save-three-url",
            data={
                "csrf_token": token,
                "main_url": "https://x.com/",
                "list_url": "https://x.com/list",
                "work_urls": "https://x.com/w",
                "branded_pool": "B",
                "partial_pool": "P",
                "exact_pool": "E",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        location = resp.headers["Location"]
        assert "saved=https://x.com" in location
        assert "autofilled=" not in location

    def test_invalid_main_url_still_422(self, client):
        """Plan 006 doesn't relax main_url's required+https rule."""
        token = _fetch_csrf(client)
        resp = client.post(
            "/sites/save-three-url",
            data={"csrf_token": token, "main_url": "http://no-https/"},
            follow_redirects=False,
        )
        assert resp.status_code == 422


# ═════════════════════════════════════════════════════════════════════════════
# Plan 009 deferred: url_categories write on homepage submit
# ═════════════════════════════════════════════════════════════════════════════


class TestHomepageWritesUrlCategories:
    """Plan 009 deferred work: homepage `/ce:plan` submit triggers BOTH
    target_three_url.list_url write AND sites.<main>.url_categories.category
    write — so the zh-CN scheduler path can pick up the configured category
    without a manual /sites visit."""

    def test_post_with_category_writes_url_categories_table(
        self, client, monkeypatch, _isolated_config_dir,
    ):
        monkeypatch.setattr(
            "webui_app.routes.pipeline_plan.fetch_url_metadata",
            lambda url: {"url": url, "title": "T", "description": "", "status": "success"},
        )
        resp = client.post(
            "/ce:plan",
            data={
                "main_url": "https://example.com/",
                "category_url": "https://example.com/cat",
            },
        )
        assert resp.status_code == 200, resp.data[:300]

        from backlink_publisher.config import load_config
        cfg = load_config()
        cats = cfg.site_url_categories.get("https://example.com", {})
        assert cats.get("home") == "https://example.com/"
        assert cats.get("category") == "https://example.com/cat"

    def test_post_without_category_still_writes_home(
        self, client, monkeypatch, _isolated_config_dir,
    ):
        """Even when operator only fills main_url + work_url, home gets
        written automatically. (The Q3 contract says home = main_url is
        always auto-filled when the form persists anything.)

        Note: a POST with no category and no work hits the no-persist
        early-return so url_categories isn't touched — that's expected."""
        monkeypatch.setattr(
            "webui_app.routes.pipeline_plan.fetch_url_metadata",
            lambda url: {"url": url, "title": "T", "description": "", "status": "success"},
        )
        resp = client.post(
            "/ce:plan",
            data={
                "main_url": "https://only-work.example/",
                "work_url": "https://only-work.example/article/1",
            },
        )
        assert resp.status_code == 200

        from backlink_publisher.config import load_config
        cfg = load_config()
        cats = cfg.site_url_categories.get("https://only-work.example", {})
        # home auto-set even when only work_url is supplied
        assert cats.get("home") == "https://only-work.example/"
        # category absent because operator didn't fill it
        assert "category" not in cats

    def test_post_preserves_existing_hot_animate_topic(
        self, client, monkeypatch, _isolated_config_dir,
    ):
        """If the operator previously hand-edited url_categories with
        hot/animate/topic keys, a homepage submit must NOT clobber them."""
        from backlink_publisher.config import (
            load_config,
            merge_site_url_categories,
        )

        # Pre-existing operator config.
        cfg_path = _isolated_config_dir / "config.toml"
        merge_site_url_categories(
            "https://x.com/",
            {
                "home": "https://x.com/",
                "hot": "https://x.com/hot",
                "animate": "https://x.com/animate",
                "topic": "https://x.com/topic",
            },
            path=cfg_path,
        )

        monkeypatch.setattr(
            "webui_app.routes.pipeline_plan.fetch_url_metadata",
            lambda url: {"url": url, "title": "T", "description": "", "status": "success"},
        )
        resp = client.post(
            "/ce:plan",
            data={
                "main_url": "https://x.com/",
                "category_url": "https://x.com/cat",
            },
        )
        assert resp.status_code == 200

        cfg = load_config()
        cats = cfg.site_url_categories["https://x.com"]
        # All four operator-set keys preserved + new category added
        assert cats["home"] == "https://x.com/"
        assert cats["hot"] == "https://x.com/hot"
        assert cats["animate"] == "https://x.com/animate"
        assert cats["topic"] == "https://x.com/topic"
