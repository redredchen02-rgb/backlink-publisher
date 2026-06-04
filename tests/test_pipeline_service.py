"""Flask-free unit tests for webui_app.services.pipeline_service (U2).

Pins the language normalization contract and input-assembly helpers extracted
from routes/pipeline.py.  No Flask app context required.
"""
from __future__ import annotations

__tier__ = "unit"
import pytest

from webui_app.services.pipeline_service import (
    build_generate_seed,
    build_plan_config,
    normalize_language,
    validate_plan_inputs,
)


# ── normalize_language ────────────────────────────────────────────────────────

class TestNormalizeLanguage:
    """SUPPORTED_LANGUAGES = {en, ko, ru, zh-CN}; others must be remapped."""

    @pytest.mark.parametrize("lang", ["zh-CN", "ko", "ru", "en"])
    def test_supported_passthrough(self, lang):
        assert normalize_language(lang) == lang

    @pytest.mark.parametrize("lang,expected", [
        ("zh-TW", "zh-CN"),
        ("ja",    "zh-CN"),
        ("es",    "en"),
        ("de",    "en"),
        ("fr",    "en"),
    ])
    def test_unsupported_remapped(self, lang, expected):
        assert normalize_language(lang) == expected

    def test_unknown_passthrough(self):
        # Unknown codes pass through unchanged (no silent coercion to a default).
        assert normalize_language("xx") == "xx"


# ── validate_plan_inputs ──────────────────────────────────────────────────────

class TestValidatePlanInputs:
    def test_all_https_returns_empty(self):
        errs = validate_plan_inputs(
            "https://main.com", "https://cat.com", "https://work.com"
        )
        assert errs == []

    def test_optional_urls_empty_ok(self):
        errs = validate_plan_inputs("https://main.com", "", "")
        assert errs == []

    def test_http_main_url_rejected(self):
        errs = validate_plan_inputs("http://main.com", "", "")
        assert len(errs) == 1
        assert "主网域" in errs[0]

    def test_http_category_url_rejected(self):
        errs = validate_plan_inputs("https://main.com", "http://cat.com", "")
        assert len(errs) == 1
        assert "分类页" in errs[0]

    def test_http_work_url_rejected(self):
        errs = validate_plan_inputs("https://main.com", "", "http://work.com")
        assert len(errs) == 1
        assert "漫画页" in errs[0]

    def test_all_http_gives_three_errors(self):
        errs = validate_plan_inputs("http://a.com", "http://b.com", "http://c.com")
        assert len(errs) == 3

    def test_empty_category_ignored(self):
        errs = validate_plan_inputs("https://main.com", "", "https://work.com")
        assert errs == []


# ── build_plan_config ─────────────────────────────────────────────────────────

class TestBuildPlanConfig:
    def test_basic_structure(self):
        cfg = build_plan_config(
            main_url="https://example.cn/",
            url_inputs=["https://example.cn/"],
            target_language="zh-CN",
            fetch_tdk="yes",
            meta_info=[],
            suggested_anchors=["anchor1"],
        )
        assert cfg["target_url"] == "https://example.cn/"
        assert cfg["main_domain"] == "https://example.cn"
        assert cfg["url_mode"] == "C"
        assert cfg["publish_mode"] == "publish"
        assert cfg["target_language"] == "zh-CN"
        assert cfg["suggested_anchors"] == ["anchor1"]
        assert cfg["fetch_tdk"] == "yes"
        assert cfg["urls"] == ["https://example.cn/"]
        assert cfg["meta_info"] == []

    def test_unsupported_language_normalized(self):
        cfg = build_plan_config(
            main_url="https://example.jp/",
            url_inputs=["https://example.jp/"],
            target_language="ja",
            fetch_tdk="no",
            meta_info=[],
            suggested_anchors=[],
        )
        assert cfg["target_language"] == "zh-CN"

    def test_tw_language_normalized(self):
        cfg = build_plan_config(
            main_url="https://example.tw/",
            url_inputs=["https://example.tw/"],
            target_language="zh-TW",
            fetch_tdk="no",
            meta_info=[],
            suggested_anchors=[],
        )
        assert cfg["target_language"] == "zh-CN"

    def test_es_language_normalized(self):
        cfg = build_plan_config(
            main_url="https://example.es/",
            url_inputs=["https://example.es/"],
            target_language="es",
            fetch_tdk="no",
            meta_info=[],
            suggested_anchors=[],
        )
        assert cfg["target_language"] == "en"


# ── build_generate_seed ───────────────────────────────────────────────────────

class TestBuildGenerateSeed:
    def _base_call(self, **overrides):
        defaults = dict(
            urls=["https://example.cn/"],
            platform="blogger",
            url_mode="C",
            publish_mode="publish",
            target_language="zh-CN",
            custom_title="",
            custom_tags="",
            tdk_data={},
        )
        defaults.update(overrides)
        return build_generate_seed(**defaults)

    def test_basic_structure(self):
        seed = self._base_call()
        assert seed["target_url"] == "https://example.cn/"
        assert seed["main_domain"] == "https://example.cn"
        assert seed["platform"] == "blogger"
        assert seed["url_mode"] == "C"
        assert seed["publish_mode"] == "publish"
        assert seed["target_language"] == "zh-CN"
        assert "language" in seed  # auto-detected

    def test_extra_urls_included(self):
        seed = self._base_call(
            urls=["https://example.cn/", "https://example.cn/page1"]
        )
        assert seed["extra_urls"] == ["https://example.cn/page1"]

    def test_no_extra_urls_key_absent(self):
        seed = self._base_call(urls=["https://example.cn/"])
        assert "extra_urls" not in seed

    def test_custom_title_included(self):
        seed = self._base_call(custom_title="My Title")
        assert seed["custom_title"] == "My Title"

    def test_empty_custom_title_excluded(self):
        seed = self._base_call(custom_title="")
        assert "custom_title" not in seed

    def test_tdk_suggested_anchors_included(self):
        seed = self._base_call(
            tdk_data={"status": "success", "suggested_anchors": ["kw1"]}
        )
        assert seed["suggested_anchors"] == ["kw1"]

    def test_tdk_failure_anchors_excluded(self):
        seed = self._base_call(
            tdk_data={"status": "error"}
        )
        assert "suggested_anchors" not in seed

    def test_language_normalized_for_jp_url(self):
        seed = self._base_call(urls=["https://example.jp/"])
        # detect_language("https://example.jp/") -> "ja" -> normalize -> "zh-CN"
        assert seed["language"] == "zh-CN"

    def test_language_normalized_for_tw_url(self):
        seed = self._base_call(urls=["https://example.tw/"])
        assert seed["language"] == "zh-CN"

    def test_language_normalized_for_es_url(self):
        seed = self._base_call(urls=["https://example.es/"])
        assert seed["language"] == "en"

    def test_target_language_normalized(self):
        seed = self._base_call(target_language="fr")
        assert seed["target_language"] == "en"

    def test_ko_language_passthrough(self):
        seed = self._base_call(urls=["https://example.kr/"])
        assert seed["language"] == "ko"
