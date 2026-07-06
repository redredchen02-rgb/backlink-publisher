"""Tests for the three-URL ``[targets."x"]`` schema parsing — Plan
2026-05-13-004 Unit 3.

D1 split (2026-07-02): this file used to also cover ``save_config``
round-tripping/critical-section preservation and the
``upgrade_target_to_threeurl`` / ``merge_site_url_categories`` helpers; those
moved to ``test_config_three_url_save.py`` and
``test_config_three_url_upgrade.py`` respectively. Shared builders
(``_write_toml``, ``_basic_three_url``) moved to
``_config_three_url_test_helpers.py`` since the save-config split file also
needs them.

Covers:
- ``_parse_target_three_url`` schema parsing (happy + every error path).
- ``ThreeUrlConfig`` defaults (``DEFAULT_WORK_TEMPLATES`` + ``insecure_tls``).
- ``get_three_url_config`` scheme/trailing-slash tolerance.
- Maintenance-mode INFO log when ``[sites.x]`` and ``[targets.x]`` coexist.
"""
from __future__ import annotations

__tier__ = "unit"
import logging

from backlink_publisher.config import (
    DEFAULT_WORK_TEMPLATES,
    get_three_url_config,
    load_config,
)
from _config_three_url_test_helpers import _write_toml

# ═════════════════════════════════════════════════════════════════════════════
# _parse_target_three_url — schema happy paths
# ═════════════════════════════════════════════════════════════════════════════


class TestParseThreeUrlHappy:
    def test_full_schema_loads_all_fields(self, tmp_path):
        body = """
[targets."https://site.com/"]
main_url = "https://site.com/"
list_url = "https://site.com/list"
work_urls = ["https://site.com/work/1", "https://site.com/work/2"]
branded_pool = ["Brand A", "Brand B"]
partial_pool = ["brand partial"]
exact_pool = ["brand"]
work_anchor_templates = ["{title}", "{title} 详情"]
list_path_blocklist = ["/tag/", "/banned/"]
insecure_tls = true
"""
        cfg = load_config(_write_toml(tmp_path, body))
        assert "https://site.com" in cfg.target_three_url
        entry = cfg.target_three_url["https://site.com"]
        assert entry.main_url == "https://site.com/"
        assert entry.list_url == "https://site.com/list"
        assert entry.work_urls == [
            "https://site.com/work/1",
            "https://site.com/work/2",
        ]
        assert entry.branded_pool == ["Brand A", "Brand B"]
        assert entry.partial_pool == ["brand partial"]
        assert entry.exact_pool == ["brand"]
        assert entry.work_anchor_templates == ["{title}", "{title} 详情"]
        assert entry.list_path_blocklist == ["/tag/", "/banned/"]
        assert entry.insecure_tls is True

    def test_only_required_fields_applies_defaults(self, tmp_path):
        body = """
[targets."https://site.com/"]
main_url = "https://site.com/"
list_url = "https://site.com/list"
branded_pool = ["Brand"]
partial_pool = ["brand partial"]
exact_pool = ["brand"]
"""
        cfg = load_config(_write_toml(tmp_path, body))
        entry = cfg.target_three_url["https://site.com"]
        assert entry.work_urls == []
        assert entry.work_anchor_templates == list(DEFAULT_WORK_TEMPLATES)
        assert entry.list_path_blocklist is None
        assert entry.insecure_tls is False

    def test_default_work_templates_have_title_placeholder(self):
        # Documenting the contract — Unit 4 relies on `{title}` substitution.
        assert all("{title}" in t for t in DEFAULT_WORK_TEMPLATES)
        assert len(DEFAULT_WORK_TEMPLATES) >= 3

    def test_trailing_slash_in_key_is_normalized(self, tmp_path):
        body = """
[targets."https://site.com"]
main_url = "https://site.com/"
list_url = "https://site.com/list"
branded_pool = ["B"]
partial_pool = ["p"]
exact_pool = ["e"]
"""
        cfg = load_config(_write_toml(tmp_path, body))
        # Stored key has no trailing slash; lookup tolerates both forms.
        assert get_three_url_config(cfg, "https://site.com") is not None
        assert get_three_url_config(cfg, "https://site.com/") is not None

    def test_get_three_url_config_returns_none_for_unknown(self, tmp_path):
        cfg = load_config(_write_toml(tmp_path, ""))
        assert get_three_url_config(cfg, "https://nope.com") is None


# ═════════════════════════════════════════════════════════════════════════════
# _parse_target_three_url — error paths
# ═════════════════════════════════════════════════════════════════════════════


class TestParseThreeUrlErrors:
    def test_non_https_main_url_skips_with_warning(self, tmp_path, caplog):
        body = """
[targets."http://site.com/"]
main_url = "http://site.com/"
list_url = "https://site.com/list"
branded_pool = ["B"]
partial_pool = ["p"]
exact_pool = ["e"]
"""
        with caplog.at_level(logging.WARNING, logger="backlink_publisher.config"):
            cfg = load_config(_write_toml(tmp_path, body))
        assert cfg.target_three_url == {}
        assert any("main_url" in r.message for r in caplog.records)

    def test_missing_list_url_skips_with_warning(self, tmp_path, caplog):
        body = """
[targets."https://site.com/"]
main_url = "https://site.com/"
branded_pool = ["B"]
partial_pool = ["p"]
exact_pool = ["e"]
"""
        with caplog.at_level(logging.WARNING, logger="backlink_publisher.config"):
            cfg = load_config(_write_toml(tmp_path, body))
        assert cfg.target_three_url == {}
        assert any("list_url" in r.message for r in caplog.records)

    def test_empty_branded_pool_skips_with_warning(self, tmp_path, caplog):
        body = """
[targets."https://site.com/"]
main_url = "https://site.com/"
list_url = "https://site.com/list"
branded_pool = []
partial_pool = ["p"]
exact_pool = ["e"]
"""
        with caplog.at_level(logging.WARNING, logger="backlink_publisher.config"):
            cfg = load_config(_write_toml(tmp_path, body))
        assert cfg.target_three_url == {}
        assert any("branded_pool" in r.message for r in caplog.records)

    def test_partial_or_exact_pool_missing_skips(self, tmp_path, caplog):
        body = """
[targets."https://site.com/"]
main_url = "https://site.com/"
list_url = "https://site.com/list"
branded_pool = ["B"]
exact_pool = ["e"]
"""
        with caplog.at_level(logging.WARNING, logger="backlink_publisher.config"):
            cfg = load_config(_write_toml(tmp_path, body))
        assert cfg.target_three_url == {}

    def test_non_https_work_url_is_filtered_out(self, tmp_path, caplog):
        body = """
[targets."https://site.com/"]
main_url = "https://site.com/"
list_url = "https://site.com/list"
work_urls = ["https://site.com/work/1", "http://site.com/insecure"]
branded_pool = ["B"]
partial_pool = ["p"]
exact_pool = ["e"]
"""
        with caplog.at_level(logging.WARNING, logger="backlink_publisher.config"):
            cfg = load_config(_write_toml(tmp_path, body))
        entry = cfg.target_three_url["https://site.com"]
        assert entry.work_urls == ["https://site.com/work/1"]

    def test_anchor_keywords_only_entry_does_not_create_three_url(self, tmp_path):
        # Backward-compat: a legacy [targets."x"] with only anchor_keywords must
        # still parse cleanly into target_anchor_keywords (NOT target_three_url).
        body = """
[targets."https://legacy.com/"]
anchor_keywords = ["legacy"]
"""
        cfg = load_config(_write_toml(tmp_path, body))
        assert cfg.target_three_url == {}
        assert cfg.target_anchor_keywords["https://legacy.com"] == ["legacy"]


# ═════════════════════════════════════════════════════════════════════════════
# Maintenance-mode INFO log when [sites.x] + [targets.x] coexist
# ═════════════════════════════════════════════════════════════════════════════


class TestMaintenanceModeLog:
    def test_coexistence_emits_info_not_warn(self, tmp_path, caplog):
        body = """
[sites."https://site.com".url_categories]
home = "https://site.com/"

[targets."https://site.com/"]
main_url = "https://site.com/"
list_url = "https://site.com/list"
branded_pool = ["B"]
partial_pool = ["p"]
exact_pool = ["e"]
"""
        with caplog.at_level(logging.INFO, logger="backlink_publisher.config"):
            cfg = load_config(_write_toml(tmp_path, body))

        # New schema parses fine — both paths coexist
        assert "https://site.com" in cfg.target_three_url
        assert "https://site.com" in cfg.site_url_categories

        # An INFO (not WARN) log mentions maintenance mode
        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert any("maintenance" in r.message.lower() for r in info_records)

        # Critically: no WARN about maintenance/deprecated (avoid old-user alarm)
        warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert not any("maintenance" in r.message.lower() for r in warn_records)
        assert not any("deprecated" in r.message.lower() for r in warn_records)
