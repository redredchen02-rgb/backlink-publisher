"""``save_config`` round-trip + critical-section preservation tests — split
from ``test_config_three_url.py`` (Plan 2026-05-13-004 Unit 3, D1 split
2026-07-02).

Covers:
- ``save_config(target_three_url=...)`` three-state semantics + round-trip.
- ``save_config`` preserves ``[blogger.oauth]`` (credential-retention regression).
- ``save_config`` preserves ``[sites.x]`` verbatim (P0 data-loss fix).
- Atomic write: a mid-write failure leaves the original file intact.
- Coexistence with legacy ``[targets."x"].anchor_keywords``.

Shared builders (``_write_toml``, ``_basic_three_url``) live in
``_config_three_url_test_helpers.py`` (also used by
``test_config_three_url.py``).
"""
from __future__ import annotations

__tier__ = "unit"
from unittest.mock import patch

import pytest

from backlink_publisher.config import load_config, save_config
from _config_three_url_test_helpers import _basic_three_url, _write_toml

# ═════════════════════════════════════════════════════════════════════════════
# save_config — three-state target_three_url + round-trip
# ═════════════════════════════════════════════════════════════════════════════


class TestSaveConfigThreeUrl:
    def test_round_trip_writes_all_fields(self, tmp_path):
        path = tmp_path / "config.toml"
        cfg = load_config(path)  # empty config
        three_url = {"https://site.com": _basic_three_url(
            work_urls=["https://site.com/work/1"],
            branded=["Brand"],
            partial=["brand partial"],
            exact=["brand"],
            list_path_blocklist=["/banned/"],
            insecure_tls=True,
        )}
        save_config(cfg, path=path, target_three_url=three_url)

        # Round-trip cycle 1
        reloaded = load_config(path)
        entry = reloaded.target_three_url["https://site.com"]
        assert entry.main_url == "https://site.com/"
        assert entry.list_url == "https://site.com/list"
        assert entry.work_urls == ["https://site.com/work/1"]
        assert entry.branded_pool == ["Brand"]
        assert entry.partial_pool == ["brand partial"]
        assert entry.exact_pool == ["brand"]
        assert entry.list_path_blocklist == ["/banned/"]
        assert entry.insecure_tls is True

        # Round-trip cycle 2 — save again with no args → preserves
        save_config(reloaded, path=path)
        reloaded2 = load_config(path)
        entry2 = reloaded2.target_three_url["https://site.com"]
        assert entry2 == entry  # exact equality across save+load+save+load

    def test_none_preserves_existing_three_url(self, tmp_path):
        path = tmp_path / "config.toml"
        cfg = load_config(path)
        save_config(
            cfg,
            path=path,
            target_three_url={"https://site.com": _basic_three_url()},
        )
        reloaded = load_config(path)
        # call save_config with target_three_url=None — should preserve
        save_config(reloaded, path=path)
        again = load_config(path)
        assert "https://site.com" in again.target_three_url

    def test_empty_dict_clears(self, tmp_path):
        path = tmp_path / "config.toml"
        save_config(
            load_config(path),
            path=path,
            target_three_url={"https://site.com": _basic_three_url()},
        )
        # Now clear
        save_config(load_config(path), path=path, target_three_url={})
        reloaded = load_config(path)
        assert reloaded.target_three_url == {}

    def test_overwrites_with_new_dict(self, tmp_path):
        path = tmp_path / "config.toml"
        save_config(
            load_config(path),
            path=path,
            target_three_url={"https://old.com": _basic_three_url(
                main_url="https://old.com/", list_url="https://old.com/list",
            )},
        )
        save_config(
            load_config(path),
            path=path,
            target_three_url={"https://new.com": _basic_three_url(
                main_url="https://new.com/", list_url="https://new.com/list",
            )},
        )
        reloaded = load_config(path)
        assert "https://old.com" not in reloaded.target_three_url
        assert "https://new.com" in reloaded.target_three_url


# ═════════════════════════════════════════════════════════════════════════════
# CRITICAL: save_config must preserve [blogger.oauth] + [sites.x]
# (P0 data-loss regression guard)
# ═════════════════════════════════════════════════════════════════════════════


class TestSaveConfigPreservesCriticalSections:
    def test_preserves_blogger_oauth(self, tmp_path):
        body = """
[blogger]
"https://site.com" = "blog-id-123"

[blogger.oauth]
client_id     = "id.apps.googleusercontent.com"
client_secret = "secret-value"
"""
        path = _write_toml(tmp_path, body)
        cfg = load_config(path)

        # Save with new three-url payload — must NOT erase OAuth credentials
        save_config(
            cfg,
            path=path,
            target_three_url={"https://site.com": _basic_three_url()},
        )
        reloaded = load_config(path)
        assert reloaded.blogger_oauth is not None
        assert reloaded.blogger_oauth.client_id == "id.apps.googleusercontent.com"
        assert reloaded.blogger_oauth.client_secret == "secret-value"

    def test_preserves_sites_section_verbatim(self, tmp_path):
        # [sites."x"] is the load-bearing read-only schema for the legacy
        # zh-CN path. save_config historically nuked it (P0 data loss).
        body = """
[blogger]
"https://51acgs.com" = "1234567890"

[sites."https://51acgs.com".url_categories]
home = "https://51acgs.com/"
hot = "https://51acgs.com/comic/hot"

[sites."https://51acgs.com".anchor_pools.home]
branded = ["51漫画"]
partial = ["成人漫画站"]
exact = ["漫画"]
lsi = ["二次元资源"]
"""
        path = _write_toml(tmp_path, body)
        cfg = load_config(path)
        assert cfg.site_url_categories  # sanity: loaded once

        save_config(
            cfg,
            path=path,
            target_three_url={"https://51acgs.com": _basic_three_url(
                main_url="https://51acgs.com/",
                list_url="https://51acgs.com/list",
            )},
        )

        reloaded = load_config(path)
        # [sites.x].url_categories survived round-trip
        assert reloaded.site_url_categories["https://51acgs.com"]["home"] \
            == "https://51acgs.com/"
        assert reloaded.site_url_categories["https://51acgs.com"]["hot"] \
            == "https://51acgs.com/comic/hot"
        # [sites.x].anchor_pools.home survived too
        from backlink_publisher.config import get_anchor_pool_v2
        assert get_anchor_pool_v2(
            reloaded, "https://51acgs.com", "home", "branded"
        ) == ["51漫画"]

    def test_preserves_anchor_proportions_and_llm_section(self, tmp_path):
        body = """
[blogger]
"https://site.com" = "1"

[anchor.proportions]
preset = "safe_seo"

[llm.anchor_provider]
base_url = "https://api.openai.com/v1"
api_key = "k"
model = "gpt-4o-mini"
"""
        path = _write_toml(tmp_path, body)
        # NB: api_key is in toml; chmod 0600 already applied in _write_toml
        cfg = load_config(path)
        save_config(cfg, path=path, target_three_url={
            "https://site.com": _basic_three_url(),
        })
        rewritten = path.read_text(encoding="utf-8")
        assert "[anchor.proportions]" in rewritten
        assert "[llm.anchor_provider]" in rewritten

    def test_atomic_write_failure_leaves_original_intact(self, tmp_path):
        body = """
[blogger]
"https://site.com" = "blog-id-original"
"""
        path = _write_toml(tmp_path, body)
        original = path.read_text(encoding="utf-8")

        # Force the inner write step to raise — by patching os.replace
        # (the final rename step). The temp file may exist briefly; the
        # invariant is the ORIGINAL path is untouched.
        with patch(
            "backlink_publisher.config.os.replace",
            side_effect=OSError("simulated rename failure"),
        ):
            with pytest.raises(OSError):
                save_config(
                    load_config(path),
                    path=path,
                    target_three_url={
                        "https://site.com": _basic_three_url(),
                    },
                )

        assert path.read_text(encoding="utf-8") == original


# ═════════════════════════════════════════════════════════════════════════════
# Coexistence with legacy [targets."x"].anchor_keywords
# ═════════════════════════════════════════════════════════════════════════════


class TestCoexistenceWithLegacyAnchorKeywords:
    def test_anchor_keywords_and_three_url_in_same_domain_block(self, tmp_path):
        path = tmp_path / "config.toml"
        cfg = load_config(path)
        save_config(
            cfg,
            path=path,
            target_anchor_keywords={"https://site.com": ["site", "site hub"]},
            target_three_url={"https://site.com": _basic_three_url()},
        )
        reloaded = load_config(path)
        assert reloaded.target_anchor_keywords["https://site.com"] == [
            "site", "site hub",
        ]
        assert "https://site.com" in reloaded.target_three_url
