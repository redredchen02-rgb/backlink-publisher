"""Tests for the YAML catalog adapter framework (Plan 2026-06-05-005 U1).

Covers schema validation, safe_load enforcement, gate-invariant rejection,
and directory loading semantics.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from backlink_publisher.publishing.adapters.catalog.catalog_schema import (
    VALID_AUTH_TYPES,
    VALID_DOFOLLOW,
    VALID_PERMALINK_VIA,
    VALID_REFERRAL,
    VALID_TOP_LEVEL_KEYS,
    CatalogValidationError,
    discover_catalog_dirs,
    load_all_entries,
    load_catalog_yaml,
    load_entries_from_dir,
    validate_entry,
)


# ── Shared helpers ────────────────────────────────────────────────────────────

_RATIONALE_80 = "x" * 80  # exactly 80 chars — minimum valid rationale


def _valid_entry(overrides: dict | None = None) -> dict:
    """Return a valid catalog entry dict (before ``slug`` set)."""
    base = {
        "slug": "testplatform",
        "endpoint": "https://test.example.com/submit",
        "auth_type": "none",
        "content_field": "body",
        "csrf_prefetch": False,
        "csrf_field_names": [],
        "permalink_via": "redirect",
        "permalink_arg": "Location",
        "min_delay_s": 0.0,
        "dofollow": True,
    }
    if overrides:
        base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# validate_entry
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidateEntry:
    """validate_entry(): dict→dict validation, error on any violation."""

    def test_happy_path_dofollow_true(self):
        """A complete dofollow=True entry passes cleanly."""
        entry = _valid_entry({"dofollow": True})
        result = validate_entry(entry, source="test")
        assert result["slug"] == "testplatform"
        assert result["dofollow"] is True
        assert result["auth_type"] == "none"
        assert result["permalink_via"] == "redirect"

    def test_happy_path_dofollow_uncertain_with_rationale(self):
        """Non-True dofollow requires rationale >= 80 chars + referral_value."""
        entry = _valid_entry({
            "dofollow": "uncertain",
            "rationale": _RATIONALE_80,
            "referral_value": "low",
        })
        result = validate_entry(entry, source="test")
        assert result["dofollow"] == "uncertain"
        assert len(result["rationale"]) >= 80
        assert result["referral_value"] == "low"

    def test_happy_path_api_key_header(self):
        """api_key_header auth type is accepted."""
        entry = _valid_entry({
            "auth_type": "api_key_header",
            "dofollow": True,
        })
        result = validate_entry(entry, source="test")
        assert result["auth_type"] == "api_key_header"

    def test_happy_path_api_key_query(self):
        """api_key_query auth type is accepted."""
        entry = _valid_entry({
            "auth_type": "api_key_query",
            "dofollow": True,
        })
        result = validate_entry(entry, source="test")
        assert result["auth_type"] == "api_key_query"

    def test_happy_path_json_path_permalink(self):
        """json_path permalink_via is accepted with permalink_arg."""
        entry = _valid_entry({
            "permalink_via": "json_path",
            "permalink_arg": "$.data.url",
            "dofollow": True,
        })
        result = validate_entry(entry, source="test")
        assert result["permalink_via"] == "json_path"
        assert result["permalink_arg"] == "$.data.url"

    def test_happy_path_regex_permalink(self):
        """regex permalink_via is accepted."""
        entry = _valid_entry({
            "permalink_via": "regex",
            "permalink_arg": r'https?://\S+',
            "dofollow": True,
        })
        result = validate_entry(entry, source="test")
        assert result["permalink_via"] == "regex"

    def test_happy_path_csrf_prefetch_enabled(self):
        """csrf_prefetch with field_names is valid."""
        entry = _valid_entry({
            "csrf_prefetch": True,
            "csrf_field_names": ["csrf_token", "form_id"],
            "dofollow": True,
        })
        result = validate_entry(entry, source="test")
        assert result["csrf_prefetch"] is True
        assert result["csrf_field_names"] == ["csrf_token", "form_id"]

    def test_happy_path_min_delay(self):
        """Positive min_delay_s is accepted."""
        entry = _valid_entry({
            "min_delay_s": 12.5,
            "dofollow": True,
        })
        result = validate_entry(entry, source="test")
        assert result["min_delay_s"] == 12.5

    # ── Failure modes ─────────────────────────────────────────────────────

    def test_missing_slug(self):
        """slug is required."""
        entry = _valid_entry({"slug": ""})
        with pytest.raises(CatalogValidationError, match="slug"):
            validate_entry(entry, source="test")

    def test_missing_endpoint(self):
        """endpoint is required."""
        entry = _valid_entry({"endpoint": ""})
        with pytest.raises(CatalogValidationError, match="endpoint"):
            validate_entry(entry, source="test")

    def test_invalid_auth_type(self):
        """auth_type must be in valid set."""
        entry = _valid_entry({"auth_type": "oauth"})
        with pytest.raises(CatalogValidationError, match="auth_type"):
            validate_entry(entry, source="test")

    def test_missing_content_field(self):
        """content_field is required."""
        entry = _valid_entry({"content_field": ""})
        with pytest.raises(CatalogValidationError, match="content_field"):
            validate_entry(entry, source="test")

    def test_invalid_permalink_via(self):
        """permalink_via must be in valid set."""
        entry = _valid_entry({"permalink_via": "xpath"})
        with pytest.raises(CatalogValidationError, match="permalink_via"):
            validate_entry(entry, source="test")

    def test_missing_permalink_arg(self):
        """permalink_arg is required."""
        entry = _valid_entry({"permalink_arg": ""})
        with pytest.raises(CatalogValidationError, match="permalink_arg"):
            validate_entry(entry, source="test")

    def test_invalid_dofollow(self):
        """dofollow must be true/false/uncertain."""
        entry = _valid_entry({"dofollow": "yes"})
        with pytest.raises(CatalogValidationError, match="dofollow"):
            validate_entry(entry, source="test")

    def test_rationale_too_short_when_not_dofollow(self):
        """rationale must be >= 80 chars when dofollow != true."""
        entry = _valid_entry({
            "dofollow": False,
            "rationale": "too short",
            "referral_value": "low",
        })
        with pytest.raises(CatalogValidationError, match="rationale"):
            validate_entry(entry, source="test")

    def test_missing_referral_value_when_not_dofollow(self):
        """referral_value required when dofollow != true."""
        entry = _valid_entry({
            "dofollow": "uncertain",
            "rationale": _RATIONALE_80,
        })
        with pytest.raises(CatalogValidationError, match="referral_value"):
            validate_entry(entry, source="test")

    def test_invalid_referral_value(self):
        """referral_value must be high or low."""
        entry = _valid_entry({
            "dofollow": False,
            "rationale": _RATIONALE_80,
            "referral_value": "medium",
        })
        with pytest.raises(CatalogValidationError, match="referral_value"):
            validate_entry(entry, source="test")

    def test_csrf_prefetch_not_boolean(self):
        """csrf_prefetch must be a boolean."""
        entry = _valid_entry({
            "csrf_prefetch": "yes",
            "dofollow": True,
        })
        with pytest.raises(CatalogValidationError, match="csrf_prefetch"):
            validate_entry(entry, source="test")

    def test_csrf_field_names_not_list(self):
        """csrf_field_names must be a list of strings."""
        entry = _valid_entry({
            "csrf_field_names": "csrf_token",
            "dofollow": True,
        })
        with pytest.raises(CatalogValidationError, match="csrf_field_names"):
            validate_entry(entry, source="test")

    def test_csrf_field_names_non_string_element(self):
        """All csrf_field_names entries must be strings."""
        entry = _valid_entry({
            "csrf_field_names": [123],
            "dofollow": True,
        })
        with pytest.raises(CatalogValidationError, match="csrf_field_names"):
            validate_entry(entry, source="test")

    def test_negative_min_delay(self):
        """min_delay_s must be non-negative."""
        entry = _valid_entry({
            "min_delay_s": -1,
            "dofollow": True,
        })
        with pytest.raises(CatalogValidationError, match="min_delay_s"):
            validate_entry(entry, source="test")

    def test_unknown_key_rejected(self):
        """Unknown keys must be rejected."""
        entry = _valid_entry({
            "dofollow": True,
            "unknown_field": "will be rejected",
        })
        with pytest.raises(CatalogValidationError, match="unknown key"):
            validate_entry(entry, source="test")

    def test_multiple_errors_reported(self):
        """Multiple violations reported together."""
        entry = _valid_entry({
            "slug": "",
            "endpoint": "",
            "dofollow": True,
        })
        with pytest.raises(CatalogValidationError) as exc:
            validate_entry(entry, source="test")
        msg = str(exc.value)
        assert "slug" in msg
        assert "endpoint" in msg


# ═══════════════════════════════════════════════════════════════════════════════
# load_catalog_yaml — safe_load enforcement
# ═══════════════════════════════════════════════════════════════════════════════

class TestLoadCatalogYaml:
    """load_catalog_yaml(): parse via safe_load only."""

    def test_empty_file_returns_none(self, tmp_path: Path):
        p = tmp_path / "empty.yaml"
        p.write_text("")
        assert load_catalog_yaml(p) is None

    def test_whitespace_only_file_returns_none(self, tmp_path: Path):
        p = tmp_path / "whitespace.yaml"
        p.write_text("\n\n  \n")
        assert load_catalog_yaml(p) is None

    def test_valid_yaml_parses(self, tmp_path: Path):
        p = tmp_path / "valid.yaml"
        p.write_text("testplatform:\n  slug: testplatform\n  endpoint: https://x.com/\n")
        result = load_catalog_yaml(p)
        assert isinstance(result, dict)
        assert result["testplatform"]["endpoint"] == "https://x.com/"

    def test_unsafe_yaml_raises(self, tmp_path: Path):
        """!!python/object tags are rejected by safe_load."""
        p = tmp_path / "unsafe.yaml"
        p.write_text("!!python/object:os.system ['ls']")
        with pytest.raises(CatalogValidationError, match="YAML parse error"):
            load_catalog_yaml(p)

    def test_malformed_yaml_raises(self, tmp_path: Path):
        """Syntax error in YAML raises CatalogValidationError."""
        p = tmp_path / "bad.yaml"
        p.write_text(": invalid indented ::: [")
        with pytest.raises(CatalogValidationError, match="YAML parse error"):
            load_catalog_yaml(p)


# ═══════════════════════════════════════════════════════════════════════════════
# load_entries_from_dir
# ═══════════════════════════════════════════════════════════════════════════════

class TestLoadEntriesFromDir:
    """load_entries_from_dir(): scan dir, load + validate all .yaml/.yml files."""

    def test_empty_dir_returns_empty(self, tmp_path: Path):
        assert load_entries_from_dir(tmp_path) == {}

    def test_single_file_loaded(self, tmp_path: Path):
        yaml_path = tmp_path / "testplatform.yaml"
        yaml_path.write_text(dedent("""\
            testplatform:
              endpoint: https://test.example.com/submit
              auth_type: none
              content_field: body
              permalink_via: redirect
              permalink_arg: Location
              dofollow: true
        """))
        entries = load_entries_from_dir(tmp_path)
        assert "testplatform" in entries
        assert entries["testplatform"]["endpoint"] == "https://test.example.com/submit"

    def test_multiple_files(self, tmp_path: Path):
        (tmp_path / "a.yaml").write_text(dedent("""\
            platform_a:
              endpoint: https://a.example.com/
              auth_type: none
              content_field: body
              permalink_via: redirect
              permalink_arg: Location
              dofollow: true
        """))
        (tmp_path / "b.yaml").write_text(dedent("""\
            platform_b:
              endpoint: https://b.example.com/
              auth_type: api_key_header
              content_field: content
              permalink_via: json_path
              permalink_arg: $.url
              dofollow: uncertain
              rationale: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
              referral_value: low
        """))
        entries = load_entries_from_dir(tmp_path)
        assert set(entries) == {"platform_a", "platform_b"}

    def test_yml_extension(self, tmp_path: Path):
        """.yml files are also picked up."""
        (tmp_path / "test.yml").write_text(dedent("""\
            testyml:
              endpoint: https://yml.example.com/
              auth_type: none
              content_field: body
              permalink_via: redirect
              permalink_arg: Location
              dofollow: true
        """))
        entries = load_entries_from_dir(tmp_path)
        assert "testyml" in entries

    def test_later_file_overwrites_earlier_slug(self, tmp_path: Path):
        """Duplicate slugs from later files overwrite earlier ones (user overlay)."""
        (tmp_path / "base.yaml").write_text(dedent("""\
            shared:
              endpoint: https://base.example.com/
              auth_type: none
              content_field: body
              permalink_via: redirect
              permalink_arg: Location
              dofollow: true
        """))
        (tmp_path / "override.yaml").write_text(dedent("""\
            shared:
              endpoint: https://override.example.com/
              auth_type: api_key_header
              content_field: body
              permalink_via: redirect
              permalink_arg: Location
              dofollow: true
        """))
        entries = load_entries_from_dir(tmp_path)
        assert entries["shared"]["endpoint"] == "https://override.example.com/"

    def test_invalid_entry_raises(self, tmp_path: Path):
        """A file with invalid content raises CatalogValidationError."""
        (tmp_path / "bad.yaml").write_text(dedent("""\
            badplatform:
              endpoint: https://bad.example.com/
              auth_type: invalid_auth
              content_field: body
              permalink_via: redirect
              permalink_arg: Location
              dofollow: true
        """))
        with pytest.raises(CatalogValidationError, match="auth_type"):
            load_entries_from_dir(tmp_path)

    def test_non_mapping_top_level_raises(self, tmp_path: Path):
        """Top-level YAML must be a mapping (dict)."""
        (tmp_path / "list.yaml").write_text("- just a list\n- not a mapping\n")
        with pytest.raises(CatalogValidationError, match="expected mapping"):
            load_entries_from_dir(tmp_path)

    def test_non_mapping_entry_raises(self, tmp_path: Path):
        """Each entry under a slug must be a mapping."""
        (tmp_path / "bad.yaml").write_text("slug_with_list:\n  - not\n  - a dict\n")
        with pytest.raises(CatalogValidationError, match="expected mapping"):
            load_entries_from_dir(tmp_path)


# ═══════════════════════════════════════════════════════════════════════════════
# discover_catalog_dirs
# ═══════════════════════════════════════════════════════════════════════════════

class TestDiscoverCatalogDirs:
    """discover_catalog_dirs(): ordered dir resolution."""

    def test_built_in_only(self, tmp_path: Path):
        built_in = str(tmp_path / "built-in")
        Path(built_in).mkdir()
        dirs = discover_catalog_dirs(built_in=built_in)
        assert len(dirs) == 1
        assert dirs[0] == Path(built_in)

    def test_built_in_and_user(self, tmp_path: Path):
        built_in = str(tmp_path / "built-in")
        user = str(tmp_path / "user")
        Path(built_in).mkdir()
        Path(user).mkdir()
        dirs = discover_catalog_dirs(built_in=built_in, user_dir=user)
        assert len(dirs) == 2
        assert dirs[0] == Path(built_in)
        assert dirs[1] == Path(user)

    def test_user_only_when_built_in_missing(self, tmp_path: Path):
        user = str(tmp_path / "user")
        Path(user).mkdir()
        dirs = discover_catalog_dirs(built_in="/nonexistent", user_dir=user)
        assert len(dirs) == 1
        assert dirs[0] == Path(user)

    def test_both_missing_returns_empty(self):
        dirs = discover_catalog_dirs(built_in="/nonexistent", user_dir="/also-missing")
        assert dirs == []


# ═══════════════════════════════════════════════════════════════════════════════
# load_all_entries — combined dir overlay
# ═══════════════════════════════════════════════════════════════════════════════

class TestLoadAllEntries:
    """load_all_entries(): built-in + user overlay."""

    def test_built_in_entries_loaded(self, tmp_path: Path):
        built_in = tmp_path / "built-in"
        built_in.mkdir()
        (built_in / "platform_a.yaml").write_text(dedent("""\
            platform_a:
              endpoint: https://a.example.com/
              auth_type: none
              content_field: body
              permalink_via: redirect
              permalink_arg: Location
              dofollow: true
        """))
        entries = load_all_entries(built_in_dir=str(built_in))
        assert "platform_a" in entries

    def test_user_dir_overrides_built_in(self, tmp_path: Path):
        built_in = tmp_path / "built-in"
        user = tmp_path / "user"
        built_in.mkdir()
        user.mkdir()

        (built_in / "shared.yaml").write_text(dedent("""\
            shared:
              endpoint: https://built-in.example.com/
              auth_type: none
              content_field: body
              permalink_via: redirect
              permalink_arg: Location
              dofollow: true
        """))
        (user / "shared.yaml").write_text(dedent("""\
            shared:
              endpoint: https://user.example.com/
              auth_type: api_key_header
              content_field: body
              permalink_via: redirect
              permalink_arg: Location
              dofollow: true
        """))

        entries = load_all_entries(
            built_in_dir=str(built_in), user_config_dir=str(user)
        )
        assert entries["shared"]["endpoint"] == "https://user.example.com/"

    def test_user_entries_merged_with_built_in(self, tmp_path: Path):
        built_in = tmp_path / "built-in"
        user = tmp_path / "user"
        built_in.mkdir()
        user.mkdir()

        (built_in / "a.yaml").write_text(dedent("""\
            platform_a:
              endpoint: https://a.example.com/
              auth_type: none
              content_field: body
              permalink_via: redirect
              permalink_arg: Location
              dofollow: true
        """))
        (user / "b.yaml").write_text(dedent("""\
            platform_b:
              endpoint: https://b.example.com/
              auth_type: api_key_header
              content_field: body
              permalink_via: redirect
              permalink_arg: Location
              dofollow: true
        """))

        entries = load_all_entries(
            built_in_dir=str(built_in), user_config_dir=str(user)
        )
        assert set(entries) == {"platform_a", "platform_b"}


# ═══════════════════════════════════════════════════════════════════════════════
# Reference catalog entry — always loadable
# ═══════════════════════════════════════════════════════════════════════════════

class TestReferenceCatalogEntry:
    """The built-in txtfyi.yaml reference entry must load and validate cleanly."""

    REFERENCE_PATH = Path(__file__).parent.parent / "src" / "backlink_publisher" / "publishing" / "adapters" / "catalog" / "txtfyi.yaml"

    def test_reference_entry_exists(self):
        assert self.REFERENCE_PATH.is_file(), (
            f"Reference catalog entry missing: {self.REFERENCE_PATH}"
        )

    def test_reference_entry_loads_and_validates(self):
        entries = load_entries_from_dir(self.REFERENCE_PATH.parent)
        assert "txtfyi" in entries
        entry = entries["txtfyi"]
        assert entry["endpoint"] == "https://txt.fyi/~/new/"
        assert entry["auth_type"] == "none"
        assert entry["dofollow"] == "uncertain"
        assert len(entry["rationale"]) >= 80
        assert entry["referral_value"] == "low"
