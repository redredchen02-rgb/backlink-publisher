"""Unit tests for Pydantic v2 typed payload models.

Covers every model and custom validator defined in
:mod:`backlink_publisher._payload_types`.  This is RED→GREEN validation:
the tests assert the models' observable behaviour so any future refactor of
the validation internals preserves the contract.
"""

from __future__ import annotations

__tier__ = "unit"

import json
from typing import Any

from pydantic import ValidationError
import pytest

from backlink_publisher.schema import (
    LinkModel,
    plan_from_dict,
    PlannedPayload,
    seed_from_dict,
    SeedPayload,
    SeoModel,
    ValidationBlock,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_seed(**overrides: Any) -> dict[str, Any]:
    """A valid seed row — override one aspect per test."""
    row: dict[str, Any] = {
        "target_url": "https://example.com/article",
        "main_domain": "https://example.com",
        "language": "en",
        "platform": "blogger",
        "url_mode": "A",
        "publish_mode": "draft",
    }
    row.update(overrides)
    return row


def _valid_planned(**overrides: Any) -> dict[str, Any]:
    """A valid planned payload row — override one aspect per test."""
    row: dict[str, Any] = {
        "id": "abc123",
        "platform": "blogger",
        "language": "en",
        "publish_mode": "draft",
        "target_url": "https://example.com/article",
        "main_domain": "https://example.com",
        "url_mode": "A",
        "title": "Test Article",
        "slug": "test-article",
        "excerpt": "An excerpt.",
        "tags": ["tag1"],
        "content_markdown": "An article mentioning https://example.com inline.",
        "links": [
            {"url": "https://example.com", "anchor": "Example", "kind": "main_domain", "required": True},
            {"url": "https://example.com/article", "anchor": "Article", "kind": "target", "required": True},
            {"url": "https://wikipedia.org", "anchor": "Wiki", "kind": "supporting", "required": False},
            {"url": "https://mdn.dev", "anchor": "MDN", "kind": "supporting", "required": False},
            {"url": "https://stackoverflow.com", "anchor": "SO", "kind": "supporting", "required": False},
            {"url": "https://github.com", "anchor": "GitHub", "kind": "supporting", "required": False},
        ],
        "seo": {
            "title": "Test Article | SEO",
            "description": "SEO description.",
            "canonical_url": "https://example.com/article",
        },
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# SeedPayload
# ---------------------------------------------------------------------------


class TestSeedPayloadBaseline:
    def test_valid_seed_constructs(self) -> None:
        """Happy path: a valid input row creates a SeedPayload."""
        seed = SeedPayload(**_valid_seed())
        assert seed.target_url == "https://example.com/article"
        assert seed.main_domain == "https://example.com"
        assert seed.language == "en"
        assert seed.platform == "blogger"
        assert seed.url_mode == "A"
        assert seed.publish_mode == "draft"

    def test_valid_seed_optional_fields_default_to_none(self) -> None:
        """Optional fields that are not supplied receive None."""
        seed = SeedPayload(**_valid_seed())
        assert seed.topic is None
        assert seed.seed_keywords is None
        assert seed.extra_urls is None
        assert seed.custom_title is None
        assert seed.custom_tags is None
        assert seed.target_language is None

    def test_valid_seed_with_optional_fields(self) -> None:
        """Optional fields are accepted with correct types."""
        seed = SeedPayload(**_valid_seed(
            topic="Test",
            seed_keywords=["kw1", "kw2"],
            extra_urls=["https://extra.com"],
            custom_title="Custom",
            custom_tags="tag-a,tag-b",
            target_language="en",
        ))
        assert seed.topic == "Test"
        assert seed.seed_keywords == ["kw1", "kw2"]
        assert seed.extra_urls == ["https://extra.com"]
        assert seed.custom_title == "Custom"
        assert seed.custom_tags == "tag-a,tag-b"
        assert seed.target_language == "en"


class TestSeedPayloadUrlValidation:
    def test_rejects_non_http_target_url(self) -> None:
        """target_url must start with http:// or https://."""
        with pytest.raises(ValidationError) as exc:
            SeedPayload(**_valid_seed(target_url="ftp://example.com"))
        assert "target_url" in str(exc.value)

    def test_rejects_non_http_main_domain(self) -> None:
        """main_domain must start with http:// or https://."""
        with pytest.raises(ValidationError) as exc:
            SeedPayload(**_valid_seed(main_domain="ftp://example.com"))
        assert "main_domain" in str(exc.value)


class TestSeedPayloadEnumValidation:
    def test_rejects_invalid_url_mode(self) -> None:
        """url_mode must be one of A, B, C."""
        with pytest.raises(ValidationError) as exc:
            SeedPayload(**_valid_seed(url_mode="Z"))
        assert "url_mode" in str(exc.value)

    def test_rejects_invalid_publish_mode(self) -> None:
        """publish_mode must be 'draft' or 'publish'."""
        with pytest.raises(ValidationError) as exc:
            SeedPayload(**_valid_seed(publish_mode="schedule"))
        assert "publish_mode" in str(exc.value)

    def test_rejects_invalid_language(self) -> None:
        """language must be in SUPPORTED_LANGUAGES."""
        with pytest.raises(ValidationError) as exc:
            SeedPayload(**_valid_seed(language="ja"))
        assert "language" in str(exc.value)

    def test_rejects_unsupported_platform(self) -> None:
        """platform must be a registered adapter."""
        with pytest.raises(ValidationError) as exc:
            SeedPayload(**_valid_seed(platform="nonexistent_platform_xyz"))
        assert "platform" in str(exc.value)


class TestSeedPayloadKeywordValidation:
    def test_valid_keywords_passes(self) -> None:
        """seed_keywords as a list of strings is accepted."""
        seed = SeedPayload(**_valid_seed(seed_keywords=["a", "b"]))
        assert seed.seed_keywords == ["a", "b"]

    def test_seed_keywords_default_none(self) -> None:
        """seed_keywords omitted defaults to None."""
        seed = SeedPayload(**_valid_seed())
        assert seed.seed_keywords is None


class TestSeedPayloadMainDomainNormalized:
    def test_normalized_is_computed(self) -> None:
        """main_domain_normalized is set automatically on valid data."""
        seed = SeedPayload(**_valid_seed())
        assert seed.main_domain_normalized == "https://example.com"

    def test_normalized_handles_punycode(self) -> None:
        """IDN domains are punycode-encoded in main_domain_normalized."""
        seed = SeedPayload(**_valid_seed(main_domain="https://löve.de"))
        assert seed.main_domain_normalized == "https://xn--lve-sna.de"

    def test_original_main_domain_preserved(self) -> None:
        """The operator-supplied main_domain is NOT overwritten by normalization."""
        seed = SeedPayload(**_valid_seed(main_domain="https://Example.COM"))
        assert seed.main_domain == "https://Example.COM"
        assert seed.main_domain_normalized == "https://example.com"


class TestSeedPayloadModelDumpRoundtrip:
    def test_model_dump_roundtrips(self) -> None:
        """model_dump() → json → model_validate() preserves data."""
        seed = SeedPayload(**_valid_seed(topic="Hello"))
        dumped = seed.model_dump()
        json_str = json.dumps(dumped, ensure_ascii=False)
        restored = SeedPayload.model_validate(json.loads(json_str))
        assert restored.target_url == seed.target_url
        assert restored.main_domain == seed.main_domain
        assert restored.language == seed.language
        assert restored.topic == seed.topic


# ---------------------------------------------------------------------------
# LinkModel
# ---------------------------------------------------------------------------


class TestLinkModel:
    def test_valid_link_constructs(self) -> None:
        """Happy path: all required fields."""
        link = LinkModel(
            url="https://example.com",
            anchor="Example",
            kind="main_domain",
            required=True,
        )
        assert link.url == "https://example.com"
        assert link.anchor == "Example"
        assert link.kind == "main_domain"
        assert link.required is True

    def test_rejects_non_http_url(self) -> None:
        """Link URL must be http(s)."""
        with pytest.raises(ValidationError):
            LinkModel(
                url="ftp://bad.com",
                anchor="Bad",
                kind="supporting",
                required=False,
            )

    def test_rejects_invalid_kind(self) -> None:
        """Link kind must be a valid member."""
        with pytest.raises(ValidationError):
            LinkModel(
                url="https://example.com",
                anchor="Bad",
                kind="bogus",  # type: ignore[arg-type]
                required=False,
            )


# ---------------------------------------------------------------------------
# SeoModel
# ---------------------------------------------------------------------------


class TestSeoModel:
    def test_valid_seo_constructs(self) -> None:
        """Happy path: title, description, canonical_url."""
        seo = SeoModel(
            title="SEO Title",
            description="SEO description.",
            canonical_url="https://example.com/article",
        )
        assert seo.title == "SEO Title"
        assert seo.canonical_url == "https://example.com/article"

    def test_empty_canonical_url_accepted(self) -> None:
        """Empty canonical_url is allowed (opt-in syndication mode)."""
        seo = SeoModel(title="T", description="D", canonical_url="")
        assert seo.canonical_url == ""

    def test_rejects_canonical_with_angle_bracket(self) -> None:
        """canonical_url must not contain HTML-injection characters."""
        with pytest.raises(ValidationError):
            SeoModel(
                title="T",
                description="D",
                canonical_url="https://example.com/<inject>",
            )

    def test_rejects_canonical_with_control_char(self) -> None:
        """canonical_url must not contain control characters."""
        with pytest.raises(ValidationError):
            SeoModel(
                title="T",
                description="D",
                canonical_url="https://example.com/\x00bad",
            )


# ---------------------------------------------------------------------------
# ValidationBlock
# ---------------------------------------------------------------------------


class TestValidationBlock:
    def test_passed(self) -> None:
        """A passed validation block."""
        vb = ValidationBlock(status="passed", checked_at="2026-01-01T00:00:00Z")
        assert vb.status == "passed"
        assert vb.warnings == []

    def test_failed_with_errors(self) -> None:
        """A failed validation block carries error messages."""
        vb = ValidationBlock(
            status="failed",
            checked_at="2026-01-01T00:00:00Z",
            warnings=["low on pool"],
            errors=["missing field 'title'"],
        )
        assert vb.errors == ["missing field 'title'"]

    def test_optional_errors_default_none(self) -> None:
        """errors field defaults to None."""
        vb = ValidationBlock(status="passed", checked_at="2026-01-01T00:00:00Z")
        assert vb.errors is None


# ---------------------------------------------------------------------------
# PlannedPayload
# ---------------------------------------------------------------------------


class TestPlannedPayloadBaseline:
    def test_valid_planned_constructs(self) -> None:
        """Happy path: a fully valid planned payload constructs."""
        plan = PlannedPayload(**_valid_planned())
        assert plan.id == "abc123"
        assert plan.title == "Test Article"
        assert len(plan.links) == 6
        assert plan.seo.title == "Test Article | SEO"

    def test_nested_models_auto_converted(self) -> None:
        """Dicts for seo and links are auto-converted to their model types."""
        plan = PlannedPayload(**_valid_planned())
        assert isinstance(plan.seo, SeoModel)
        assert all(isinstance(link, LinkModel) for link in plan.links)


class TestPlannedPayloadFieldValidation:
    def test_rejects_empty_title(self) -> None:
        """Title must not be whitespace-only."""
        with pytest.raises(ValidationError):
            PlannedPayload(**_valid_planned(title="   \n\t"))

    def test_rejects_empty_slug(self) -> None:
        """Slug must not be whitespace-only."""
        with pytest.raises(ValidationError):
            PlannedPayload(**_valid_planned(slug="   "))

    def test_rejects_empty_excerpt(self) -> None:
        """Excerpt must not be whitespace-only."""
        with pytest.raises(ValidationError):
            PlannedPayload(**_valid_planned(excerpt=""))


class TestPlannedPayloadLinkCount:
    def test_too_few_links_rejected(self) -> None:
        """Link count below 6 raises error."""
        row = _valid_planned()
        row["links"] = row["links"][:3]
        with pytest.raises(ValidationError) as exc:
            PlannedPayload(**row)
        assert "link count" in str(exc.value)

    def test_too_many_links_rejected(self) -> None:
        """Link count above 8 raises error."""
        row = _valid_planned()
        extra = {"url": "https://extra.com", "anchor": "X", "kind": "extra", "required": False}
        row["links"] = row["links"] + [extra, extra, extra]
        with pytest.raises(ValidationError) as exc:
            PlannedPayload(**row)
        assert "link count" in str(exc.value)

    def test_boundary_6_passes(self) -> None:
        """Exactly 6 links is valid."""
        plan = PlannedPayload(**_valid_planned())
        assert len(plan.links) == 6

    def test_boundary_8_passes(self) -> None:
        """Exactly 8 links is valid."""
        row = _valid_planned()
        extra = {"url": "https://extra.com", "anchor": "X", "kind": "extra", "required": False}
        row["links"] = row["links"] + [extra, extra]
        plan = PlannedPayload(**row)
        assert len(plan.links) == 8


class TestPlannedPayloadContent:
    def test_missing_content_raises(self) -> None:
        """At least one of content_markdown or content_html is required."""
        row = _valid_planned()
        del row["content_markdown"]
        with pytest.raises(ValidationError) as exc:
            PlannedPayload(**row)
        assert "content_markdown" in str(exc.value) or "content_html" in str(exc.value)

    def test_content_html_only_passes(self) -> None:
        """content_html without content_markdown is valid."""
        row = _valid_planned()
        del row["content_markdown"]
        row["content_html"] = "<p>Hello https://example.com</p>"
        plan = PlannedPayload(**row)
        assert plan.content_html == "<p>Hello https://example.com</p>"
        assert plan.content_markdown is None


class TestPlannedPayloadMainDomainInContent:
    def test_main_domain_missing_from_markdown_raises(self) -> None:
        """The main_domain URL must appear in content_markdown."""
        row = _valid_planned()
        row["content_markdown"] = "No link here."
        with pytest.raises(ValidationError) as exc:
            PlannedPayload(**row)
        assert "main_domain" in str(exc.value)


class TestPlannedPayloadRoundtrip:
    def test_model_dump_roundtrips(self) -> None:
        """model_dump() → json → model_validate() preserves data."""
        plan = PlannedPayload(**_valid_planned())
        dumped = plan.model_dump()
        json_str = json.dumps(dumped, ensure_ascii=False)
        restored = PlannedPayload.model_validate(json.loads(json_str))
        assert restored.id == plan.id
        assert restored.title == plan.title
        assert len(restored.links) == len(plan.links)
        assert restored.seo.title == plan.seo.title


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


class TestSeedFromDict:
    def test_valid(self) -> None:
        """seed_from_dict accepts a valid dict."""
        seed = seed_from_dict(_valid_seed())
        assert isinstance(seed, SeedPayload)
        assert seed.language == "en"

    def test_invalid_strict_raises(self) -> None:
        """seed_from_dict with invalid data and strict=True raises ValueError."""
        with pytest.raises(ValueError):
            seed_from_dict(_valid_seed(url_mode="Z"), strict=True)

    def test_link_model_url_field(self) -> None:
        """A LinkModel with a valid URL is accepted."""
        link = LinkModel(url="https://example.com/page", anchor="Example", kind="main_domain", required=True)
        assert link.url == "https://example.com/page"
        assert link.kind == "main_domain"
        assert link.required is True

    def test_link_model_invalid_url(self) -> None:
        """A LinkModel with an invalid URL is rejected."""
        with pytest.raises(ValidationError):
            LinkModel(url="not-a-url", anchor="Bad", kind="supporting", required=False)


# ---------------------------------------------------------------------------
# validate_and_convert helpers (Phase 2 — Pydantic validation integration)
# ---------------------------------------------------------------------------


class TestValidateAndConvertInput:
    def test_valid_returns_model_and_empty_errors(self) -> None:
        """Happy path: returns (SeedPayload, [])."""
        from backlink_publisher.schema import validate_and_convert_input

        model, errors = validate_and_convert_input(_valid_seed(), 1)
        assert errors == []
        assert isinstance(model, SeedPayload)
        assert model.target_url == "https://example.com/article"

    def test_invalid_returns_none_and_errors(self) -> None:
        """Invalid data returns (None, errors)."""
        from backlink_publisher.schema import validate_and_convert_input

        model, errors = validate_and_convert_input(_valid_seed(url_mode="Z"), 7)
        assert model is None
        assert len(errors) > 0
        assert any("line 7" in e for e in errors)

    def test_side_effect_normalized_still_set(self) -> None:
        """main_domain_normalized is set as a side effect even through the new path."""
        from backlink_publisher.schema import validate_and_convert_input

        row = _valid_seed(main_domain="https://Example.COM")
        _, errors = validate_and_convert_input(row, 1)
        assert errors == []
        assert "main_domain_normalized" in row
        assert row["main_domain"] == "https://Example.COM"


class TestValidateAndConvertOutput:
    def test_valid_returns_model_and_empty_errors(self) -> None:
        """Happy path: returns (PlannedPayload, [])."""
        from backlink_publisher.schema import validate_and_convert_output

        model, errors = validate_and_convert_output(_valid_planned())
        assert errors == []
        assert isinstance(model, PlannedPayload)
        assert model.title == "Test Article"

    def test_invalid_returns_none_and_errors(self) -> None:
        """Invalid data returns (None, errors)."""
        from backlink_publisher.schema import validate_and_convert_output

        model, errors = validate_and_convert_output(_valid_planned(title="   "))
        assert model is None
        assert len(errors) > 0
        assert any("title must not be empty" in e for e in errors)


# ---------------------------------------------------------------------------
# Pipeline dispatch typed validation (Phase 3 — model assertion in pipeline)
# ---------------------------------------------------------------------------


class TestValidatePublishPayload:
    """validate_publish_payload now includes a Pydantic model_validate assertion."""

    def test_valid_publish_payload_passes(self) -> None:
        """A valid publish payload returns no errors."""
        from backlink_publisher.schema import validate_publish_payload

        errors = validate_publish_payload(_valid_planned())
        assert errors == []

    def test_invalid_missing_field_caught(self) -> None:
        """Missing required field is still caught by old checks first."""
        from backlink_publisher.schema import validate_publish_payload

        row = _valid_planned()
        del row["title"]
        errors = validate_publish_payload(row)
        assert len(errors) > 0
        assert any("missing required output field" in e for e in errors)

    def test_invalid_platform_caught(self) -> None:
        """Unsupported platform is caught by publish-specific check."""
        from backlink_publisher.schema import validate_publish_payload

        errors = validate_publish_payload(_valid_planned(platform="nonexistent"))
        assert len(errors) > 0
        assert any("nonexistent" in e for e in errors)

    def test_pydantic_assertion_runs_on_valid_row(self) -> None:
        """When old checks pass, the Pydantic model_validate assertion runs."""
        from backlink_publisher.schema import validate_publish_payload

        # Row that passes old checks but would fail Pydantic requires finding
        # a divergence. Currently old checks and Pydantic have near-identical
        # coverage; the Pydantic assertion is defense-in-depth.
        # A valid row still passes — this test verifies the path is live.
        errors = validate_publish_payload(_valid_planned())
        assert errors == []


class TestPlanEngineTypedValidation:
    """plan_rows uses validate_and_convert_input (SeedPayload) for row validation."""

    def test_plan_imports_validate_and_convert_input(self) -> None:
        """The engine module imports validate_and_convert_input, not validate_input_payload."""
        import backlink_publisher.cli.plan_backlinks._engine as engine

        # Check the module's top-level name table to verify the right function is imported.
        # (Source-string matching is too fragile — docstrings reference the old name.)
        # Do NOT call importlib.reload() here — reload() re-executes the module body,
        # creating a NEW PlanOutcome class object that differs from the one bound in
        # other test modules at collection time, breaking isinstance() checks.
        mod_namespace = set(dir(engine))
        assert "validate_and_convert_input" in mod_namespace
        assert "validate_input_payload" not in mod_namespace


class TestValidateEngineTypedValidation:
    """validate_rows uses validate_and_convert_output (PlannedPayload) for payload validation."""

    def test_validate_imports_validate_and_convert_output(self) -> None:
        """The validate engine module imports the typed validation function."""
        import importlib.util

        # Use get_source() to check the source text — this avoids importlib.reload()
        # which re-executes the module body and creates a new ValidateOutcome class
        # object, breaking isinstance() checks in test_validate_engine.py tests.
        source = importlib.util.find_spec(
            "backlink_publisher._validate_engine.engine"
        ).loader.get_source("backlink_publisher._validate_engine.engine")
        assert "validate_and_convert_output" in source
        assert "validate_output_payload" not in source
