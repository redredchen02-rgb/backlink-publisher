"""``upgrade_target_to_threeurl`` + ``merge_site_url_categories`` tests —
split from ``test_config_three_url.py`` (D1 split, 2026-07-02).

Covers:
- ``upgrade_target_to_threeurl`` (Plan 2026-05-14-009 Unit 3): bootstrap,
  legacy anchor_keywords migration (scheme-exact and bare-domain key),
  merge-existing (only provided fields overwritten), and round-trip through
  ``save_config``/``load_config``.
- ``merge_site_url_categories`` (Plan 009 deferred work): in-place TOML merge
  for ``[sites."<main>".url_categories]``, preserving operator-curated keys.

No shared helpers needed here — unlike the other two split files, this one
doesn't touch ``_write_toml``/``_basic_three_url``.
"""
from __future__ import annotations

__tier__ = "unit"
import pytest

from backlink_publisher.config import load_config, save_config, ThreeUrlConfig

# ═════════════════════════════════════════════════════════════════════════════
# upgrade_target_to_threeurl (Plan 2026-05-14-009 Unit 3)
# ═════════════════════════════════════════════════════════════════════════════


class TestUpgradeTargetToThreeUrl:
    """Pure-function helper that derives a ThreeUrlConfig from current
    Config state. Three migration paths: merge-existing, anchor_keywords,
    bootstrap. Caller writes the result back via save_config."""

    def test_domain_label_basic(self):
        from backlink_publisher.config import _domain_label
        assert _domain_label("https://51acgs.com/") == "51acgs"
        assert _domain_label("https://www.51acgs.com/") == "51acgs"
        assert _domain_label("https://a.b.c.com/") == "a"
        assert _domain_label("https://example.com") == "example"

    def test_bootstrap_no_prior_state(self, tmp_path):
        """Unknown main_url → all pools fall back to domain_label."""
        from backlink_publisher.config import upgrade_target_to_threeurl

        cfg = load_config(tmp_path / "config.toml")
        result = upgrade_target_to_threeurl(
            cfg,
            main_url="https://newsite.com/",
            category_url="https://newsite.com/category",
            work_url="https://newsite.com/article/1",
        )

        assert result.main_url == "https://newsite.com/"
        assert result.list_url == "https://newsite.com/category"
        assert result.branded_pool == ["newsite"]
        assert result.partial_pool == ["newsite"]
        assert result.exact_pool == ["newsite"]
        assert result.work_urls == ["https://newsite.com/article/1"]

    def test_bootstrap_only_main_url(self, tmp_path):
        """No category / work supplied — list_url falls back to main_url,
        work_urls is empty."""
        from backlink_publisher.config import upgrade_target_to_threeurl

        cfg = load_config(tmp_path / "config.toml")
        result = upgrade_target_to_threeurl(
            cfg, main_url="https://bare.com/",
        )
        assert result.list_url == "https://bare.com/"
        assert result.work_urls == []
        assert result.branded_pool == ["bare"]

    def test_legacy_anchor_keywords_migrated_to_branded_pool(self, tmp_path):
        """Pre-existing anchor_keywords (legacy schema) → branded_pool."""
        path = tmp_path / "config.toml"
        save_config(
            load_config(path), path=path,
            target_anchor_keywords={
                "https://legacy.com": ["LegacyBrand", "legacy hub", "legacy"],
            },
        )
        cfg = load_config(path)

        from backlink_publisher.config import upgrade_target_to_threeurl
        result = upgrade_target_to_threeurl(
            cfg,
            main_url="https://legacy.com",
            category_url="https://legacy.com/cat",
            work_url="https://legacy.com/work/9",
        )

        assert result.branded_pool == ["LegacyBrand", "legacy hub", "legacy"]
        # Other pools still fall back to domain_label (schema requires non-empty)
        assert result.partial_pool == ["legacy"]
        assert result.exact_pool == ["legacy"]
        assert result.list_url == "https://legacy.com/cat"
        assert result.work_urls == ["https://legacy.com/work/9"]

    def test_legacy_anchor_keywords_bare_domain_key_migrated(self, tmp_path):
        """Regression: a legacy pool keyed by the BARE domain (no scheme) must
        still migrate. Stored keys are rstrip('/')-normalised but keep whatever
        scheme the operator wrote; the upgrade path previously only matched the
        scheme-exact key, so a ``[targets."legacy.com"]`` pool was silently
        dropped and the target bootstrapped to just the domain label."""
        path = tmp_path / "config.toml"
        save_config(
            load_config(path), path=path,
            target_anchor_keywords={
                "legacy.com": ["LegacyBrand", "legacy hub", "legacy"],
            },
        )
        cfg = load_config(path)

        from backlink_publisher.config import upgrade_target_to_threeurl
        result = upgrade_target_to_threeurl(
            cfg, main_url="https://legacy.com",
        )

        # Found via the bare-domain variant → migrated, NOT bootstrapped.
        assert result.branded_pool == ["LegacyBrand", "legacy hub", "legacy"]

    def test_existing_threeurl_config_merges_only_provided_fields(self, tmp_path):
        """If a full ThreeUrlConfig already exists, only list_url and work_urls
        are overwritten when the corresponding kwargs are non-None. Other
        pools / templates / flags inherit from the existing entry."""
        path = tmp_path / "config.toml"
        existing = ThreeUrlConfig(
            main_url="https://full.com/",
            list_url="https://full.com/old-list",
            branded_pool=["FullBrand"],
            partial_pool=["partial1"],
            exact_pool=["exact1"],
            work_urls=["https://full.com/old-work"],
            insecure_tls=True,
        )
        save_config(
            load_config(path), path=path,
            target_three_url={"https://full.com": existing},
        )
        cfg = load_config(path)

        from backlink_publisher.config import upgrade_target_to_threeurl
        result = upgrade_target_to_threeurl(
            cfg,
            main_url="https://full.com/",
            category_url="https://full.com/new-list",
            work_url="https://full.com/new-work",
        )

        # list_url + work_urls overwritten; other fields preserved.
        assert result.list_url == "https://full.com/new-list"
        assert result.work_urls == ["https://full.com/new-work"]
        assert result.branded_pool == ["FullBrand"]
        assert result.partial_pool == ["partial1"]
        assert result.exact_pool == ["exact1"]
        assert result.insecure_tls is True

    def test_existing_threeurl_without_new_work_url_preserves_existing_work_urls(
        self, tmp_path,
    ):
        """If work_url is None, the existing entry's work_urls list is kept
        intact (operator may have curated it via /sites)."""
        path = tmp_path / "config.toml"
        existing = ThreeUrlConfig(
            main_url="https://x.com/",
            list_url="https://x.com/list",
            branded_pool=["X"],
            partial_pool=["x"],
            exact_pool=["x"],
            work_urls=["https://x.com/a", "https://x.com/b", "https://x.com/c"],
        )
        save_config(
            load_config(path), path=path,
            target_three_url={"https://x.com": existing},
        )
        cfg = load_config(path)

        from backlink_publisher.config import upgrade_target_to_threeurl
        result = upgrade_target_to_threeurl(
            cfg, main_url="https://x.com/",
        )
        assert result.work_urls == [
            "https://x.com/a", "https://x.com/b", "https://x.com/c",
        ]

    def test_integration_result_passes_schema_validation_after_roundtrip(
        self, tmp_path,
    ):
        """Upgrade → save_config → load_config: the upgraded ThreeUrlConfig
        survives the round-trip without the schema enforcement (three pools
        non-empty) stripping the entry."""
        from backlink_publisher.config import upgrade_target_to_threeurl

        path = tmp_path / "config.toml"
        cfg = load_config(path)
        result = upgrade_target_to_threeurl(
            cfg,
            main_url="https://roundtrip.com/",
            category_url="https://roundtrip.com/cat",
            work_url="https://roundtrip.com/w1",
        )
        save_config(
            cfg, path=path,
            target_three_url={"https://roundtrip.com": result},
        )

        reloaded = load_config(path)
        assert "https://roundtrip.com" in reloaded.target_three_url
        rt = reloaded.target_three_url["https://roundtrip.com"]
        assert rt.list_url == "https://roundtrip.com/cat"
        assert rt.work_urls == ["https://roundtrip.com/w1"]
        # All three pools non-empty (schema invariant).
        assert len(rt.branded_pool) >= 1
        assert len(rt.partial_pool) >= 1
        assert len(rt.exact_pool) >= 1


# ═════════════════════════════════════════════════════════════════════════════
# merge_site_url_categories — in-place TOML merge (Plan 009 deferred work)
# ═════════════════════════════════════════════════════════════════════════════


class TestMergeSiteUrlCategories:
    """In-place TOML merge for [sites."<main>".url_categories]. Closes
    brainstorm Q3: homepage form writes category_url to BOTH
    target_three_url.list_url AND sites.<main>.url_categories.category.
    Existing operator-curated keys (hot, animate, topic) are preserved."""

    def test_creates_new_section_when_absent(self, tmp_path):
        from backlink_publisher.config import (
            merge_site_url_categories,
        )

        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text(
            '[blogger]\n"https://x.com" = "1"\n', encoding="utf-8",
        )
        merge_site_url_categories(
            "https://x.com/",
            {"home": "https://x.com/", "category": "https://x.com/cat"},
            path=cfg_path,
        )
        content = cfg_path.read_text(encoding="utf-8")
        assert '[sites."https://x.com".url_categories]' in content
        assert 'home = "https://x.com/"' in content
        assert 'category = "https://x.com/cat"' in content

    def test_preserves_existing_unrelated_keys(self, tmp_path):
        from backlink_publisher.config import merge_site_url_categories

        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text(
            '[blogger]\n"https://x.com" = "1"\n\n'
            '[sites."https://x.com".url_categories]\n'
            'home = "https://x.com/"\n'
            'hot = "https://x.com/hot"\n'
            'animate = "https://x.com/animate"\n'
            'topic = "https://x.com/topic"\n',
            encoding="utf-8",
        )
        merge_site_url_categories(
            "https://x.com/",
            {"category": "https://x.com/cat"},
            path=cfg_path,
        )
        content = cfg_path.read_text(encoding="utf-8")
        # hot/animate/topic preserved verbatim
        assert 'hot = "https://x.com/hot"' in content
        assert 'animate = "https://x.com/animate"' in content
        assert 'topic = "https://x.com/topic"' in content
        # new key appended
        assert 'category = "https://x.com/cat"' in content

    def test_overwrites_existing_same_key(self, tmp_path):
        from backlink_publisher.config import merge_site_url_categories

        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text(
            '[sites."https://x.com".url_categories]\n'
            'category = "https://x.com/old-cat"\n'
            'hot = "https://x.com/hot"\n',
            encoding="utf-8",
        )
        merge_site_url_categories(
            "https://x.com/",
            {"category": "https://x.com/NEW-cat"},
            path=cfg_path,
        )
        content = cfg_path.read_text(encoding="utf-8")
        assert 'category = "https://x.com/NEW-cat"' in content
        assert 'category = "https://x.com/old-cat"' not in content
        # Unrelated key still present
        assert 'hot = "https://x.com/hot"' in content

    def test_load_config_round_trip(self, tmp_path):
        """After the merge, load_config can parse the section back into
        Config.site_url_categories with all keys present."""
        from backlink_publisher.config import (
            load_config,
            merge_site_url_categories,
        )

        cfg_path = tmp_path / "config.toml"
        merge_site_url_categories(
            "https://x.com/",
            {"home": "https://x.com/", "category": "https://x.com/cat"},
            path=cfg_path,
        )
        cfg = load_config(cfg_path)
        cats = cfg.site_url_categories.get("https://x.com", {})
        assert cats.get("home") == "https://x.com/"
        assert cats.get("category") == "https://x.com/cat"

    def test_empty_additions_is_noop(self, tmp_path):
        from backlink_publisher.config import merge_site_url_categories

        cfg_path = tmp_path / "config.toml"
        original = '[blogger]\n"https://x.com" = "1"\n'
        cfg_path.write_text(original, encoding="utf-8")
        merge_site_url_categories(
            "https://x.com/", {}, path=cfg_path,
        )
        assert cfg_path.read_text(encoding="utf-8") == original

    def test_writes_to_nonexistent_file(self, tmp_path):
        """Operator may not have a config.toml yet — first write should
        create one rather than fail."""
        from backlink_publisher.config import merge_site_url_categories

        cfg_path = tmp_path / "fresh-config.toml"
        assert not cfg_path.exists()
        merge_site_url_categories(
            "https://x.com/",
            {"home": "https://x.com/"},
            path=cfg_path,
        )
        assert cfg_path.exists()
        content = cfg_path.read_text(encoding="utf-8")
        assert "[sites." in content
        assert 'home = "https://x.com/"' in content

    def test_snapshot_taken_before_overwrite(self, tmp_path):
        """When the file exists, _snapshot_config copies it into
        .config-history/ before our merge writes. Mirrors save_config's
        safety net."""
        from backlink_publisher.config import merge_site_url_categories

        cfg_path = tmp_path / "config.toml"
        cfg_path.write_text(
            '[sites."https://x.com".url_categories]\nold_key = "old"\n',
            encoding="utf-8",
        )
        merge_site_url_categories(
            "https://x.com/",
            {"category": "https://x.com/cat"},
            path=cfg_path,
        )
        history = (tmp_path / ".config-history")
        assert history.exists() and history.is_dir()
        snapshots = list(history.iterdir())
        assert len(snapshots) >= 1, "expected at least one snapshot"

    def test_control_char_in_main_url_rejected(self, tmp_path):
        """Defence against malformed main_url that would break the TOML
        basic string quoting. The webui handler validates main_url
        upstream, but defensive rejection at this layer is cheap."""
        from backlink_publisher._util.errors import InputValidationError
        from backlink_publisher.config import merge_site_url_categories

        cfg_path = tmp_path / "config.toml"
        with pytest.raises(InputValidationError):
            merge_site_url_categories(
                "https://x.com/\nmalicious=true",
                {"home": "x"},
                path=cfg_path,
            )
