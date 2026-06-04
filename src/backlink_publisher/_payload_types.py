"""Pydantic v2 typed models for backlink pipeline payloads.

This module defines the authoritative schema for all JSONL payloads flowing
through the publishing pipeline. Each model corresponds to a processing stage:

- :class:`SeedPayload` — input seed row (``plan-backlinks`` input).
- :class:`PlannedPayload` — planned article payload (``plan-backlinks`` output).
- :class:`ValidationBlock` — validation-result envelope (added by
  ``validate-backlinks``).
- :class:`LinkModel` — single backlink entry within a payload.
- :class:`SeoModel` — SEO metadata block within a payload.

Using these models is **opt-in** in v1 — the existing ``dict[str, Any]``
validation functions in :mod:`backlink_publisher.schema` remain unchanged.
Consumers that want typed payloads can:

.. code-block:: python

    from backlink_publisher.schema import SeedPayload, PlannedPayload

    seed = SeedPayload(**raw_dict)             # validate + convert
    plan = PlannedPayload.model_validate(raw)  # alternative entry point
    data = plan.model_dump()                   # back to dict for JSONL

All models round-trip cleanly through ``model_dump()`` → ``json.dumps()`` →
``json.loads()`` → ``model_validate()`` for JSONL pipe compatibility.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Constants — shared with schema.py
# ---------------------------------------------------------------------------

#: Accepted URL schemes for backlink payload fields.
_URL_SCHEME_RE = re.compile(r"^https?://")

#: Cap on ``content_html`` byte length (defends regex/parser from bomb input).
_MAX_CONTENT_HTML_BYTES = 1_048_576  # 1 MiB

#: Canonical URL regex — rejects control chars, whitespace, quotes, angle
#: brackets, and backticks (security: injection prevention across HTML
#: attribute / HTML element / YAML newline / GraphQL string-escape vectors).
_CANONICAL_URL_RE = re.compile(
    r"^https?://[^\s\"'<>`\x00-\x1f\x7f]+$", re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class LinkModel(BaseModel):
    """A single backlink entry within a planned payload.

    Corresponds to one element of the ``links`` array in the output schema.
    """

    url: str
    anchor: str
    kind: Literal[
        "main_domain", "target", "supporting", "extra", "category", "detail"
    ]
    required: bool

    @field_validator("url")
    @classmethod
    def _check_url_scheme(cls, v: str) -> str:
        if not _URL_SCHEME_RE.match(v):
            raise ValueError(f"invalid URL format: {v}")
        return v


class SeoModel(BaseModel):
    """SEO metadata block within a planned payload.

    Corresponds to the ``seo`` dict in the output schema.
    """

    title: str
    description: str
    canonical_url: str

    @field_validator("canonical_url")
    @classmethod
    def _check_canonical_url(cls, v: str) -> str:
        if v and not _CANONICAL_URL_RE.match(v):
            raise ValueError(
                f"canonical_url is not a valid http(s) URL "
                f"(must match ^https?:// and contain no whitespace, "
                f"quotes, angle brackets, backticks, or control chars): {v!r}"
            )
        return v


class ValidationBlock(BaseModel):
    """Validation-result envelope appended by ``validate-backlinks``.

    Corresponds to the ``validation`` block carried in enriched payloads.
    """

    status: Literal["passed", "failed"]
    checked_at: str
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] | None = None


# ---------------------------------------------------------------------------
# Input seed payload
# ---------------------------------------------------------------------------


class SeedPayload(BaseModel):
    """Input seed row — the first stage of the publishing pipeline.

    Schema mirrors :data:`backlink_publisher.schema.INPUT_SCHEMA_FIELDS` and
    :data:`backlink_publisher.schema.INPUT_OPTIONAL_FIELDS`.

    The ``main_domain_normalized`` field is computed automatically during
    validation via IDN punycode encoding.

    Usage:

    .. code-block:: python

        seed = SeedPayload(**raw_dict)  # validates on construction
        seed.main_domain_normalized      # computed side-effect
        seed.model_dump()                # back to plain dict for JSONL
    """

    # -- required fields ---------------------------------------------------
    target_url: str
    main_domain: str
    language: str
    platform: str
    url_mode: Literal["A", "B", "C"]
    publish_mode: Literal["draft", "publish"]

    # -- optional fields ---------------------------------------------------
    topic: str | None = None
    seed_keywords: list[str] | None = None
    extra_urls: list[str] | None = None
    custom_title: str | None = None
    custom_tags: str | None = None
    target_language: str | None = None

    # -- computed side-effect (see model_validator) ------------------------
    main_domain_normalized: str | None = None

    # -- field validators --------------------------------------------------

    @field_validator("target_url", "main_domain")
    @classmethod
    def _check_url_scheme(cls, v: str) -> str:
        if not _URL_SCHEME_RE.match(v):
            raise ValueError(f"field '{v}' is not a valid URL: must start with http:// or https://")
        return v

    @field_validator("language")
    @classmethod
    def _check_language(cls, v: str) -> str:
        # Lazy import to avoid circular dependency at module level.
        from backlink_publisher.linkcheck.language import SUPPORTED_LANGUAGES

        if v not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"unsupported language '{v}'. "
                f"Supported: {', '.join(sorted(SUPPORTED_LANGUAGES))}"
            )
        return v

    @field_validator("platform")
    @classmethod
    def _check_platform(cls, v: str) -> str:
        # Lazy import: triggers adapter registry registration.
        from backlink_publisher.schema import supported_platforms

        supported = supported_platforms()
        if v not in supported:
            raise ValueError(
                f"unsupported platform '{v}'. "
                f"Supported: {', '.join(sorted(supported))}"
            )
        return v

    @field_validator("seed_keywords")
    @classmethod
    def _check_seed_keywords(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            for i, kw in enumerate(v):
                if not isinstance(kw, str):
                    raise ValueError(f"'seed_keywords' item at index {i} must be a string, got {type(kw).__name__}")
        return v

    # -- model-level validators -------------------------------------------

    @model_validator(mode="after")
    def _normalize_main_domain(self) -> SeedPayload:
        """Compute IDN-encoded ``main_domain_normalized`` from ``main_domain``.

        Preserves the original ``main_domain`` verbatim — the normalized form
        is stored on the separate ``main_domain_normalized`` field.
        """
        if self.main_domain and not _URL_SCHEME_RE.match(self.main_domain):
            return self  # URL scheme error will be caught by _check_url_scheme
        from backlink_publisher.schema import _normalize_main_domain

        try:
            normalized = _normalize_main_domain(self.main_domain)
            object.__setattr__(self, "main_domain_normalized", normalized)
        except ValueError:
            pass  # handled by validate_input_payload in the legacy path
        return self


# ---------------------------------------------------------------------------
# Output planned payload
# ---------------------------------------------------------------------------


class PlannedPayload(BaseModel):
    """Planned article payload — the output of ``plan-backlinks``.

    Schema mirrors :data:`backlink_publisher.schema.OUTPUT_REQUIRED_FIELDS`
    and :data:`backlink_publisher.schema.OUTPUT_OPTIONAL_FIELDS`.

    Usage:

    .. code-block:: python

        plan = PlannedPayload(**raw_dict)         # validates on construction
        plan.model_dump()                          # back to JSONL-serializable dict
        plan.model_dump(mode="json")               # JSON-native types only
    """

    # -- required fields ---------------------------------------------------
    id: str
    platform: str
    language: str
    publish_mode: Literal["draft", "publish"]
    target_url: str
    main_domain: str
    url_mode: Literal["A", "B", "C"]
    title: str
    slug: str
    excerpt: str
    tags: list[str]
    links: list[LinkModel]
    seo: SeoModel

    # -- optional fields ---------------------------------------------------
    content_markdown: str | None = None
    content_html: str | None = None
    main_domain_normalized: str | None = None

    # -- field validators --------------------------------------------------

    @field_validator("title", "slug", "excerpt")
    @classmethod
    def _check_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(f"must not be empty")
        return v

    @field_validator("content_html")
    @classmethod
    def _check_content_html_size(cls, v: str | None) -> str | None:
        if v is not None:
            size = len(v.encode("utf-8"))
            if size > _MAX_CONTENT_HTML_BYTES:
                raise ValueError(
                    f"content_html size {size} bytes exceeds "
                    f"{_MAX_CONTENT_HTML_BYTES} byte cap"
                )
        return v

    # -- model-level validators -------------------------------------------

    @model_validator(mode="after")
    def _check_one_of_groups(self) -> PlannedPayload:
        """At least one of ``content_markdown`` / ``content_html`` must be present."""
        if not self.content_markdown and not self.content_html:
            raise ValueError(
                "at least one of ('content_markdown', 'content_html') "
                "must be present and non-empty"
            )
        return self

    @model_validator(mode="after")
    def _check_link_count(self) -> PlannedPayload:
        """A backlink article carries 6–8 links."""
        n = len(self.links)
        if n < 6 or n > 8:
            raise ValueError(f"link count {n} is not between 6 and 8")
        return self

    @model_validator(mode="after")
    def _check_main_domain_in_content(self) -> PlannedPayload:
        """The ``main_domain`` URL must appear in ``content_markdown`` when present."""
        if self.content_markdown and self.main_domain:
            md_domain = self.main_domain.rstrip("/")
            if md_domain not in self.content_markdown and self.main_domain not in self.content_markdown:
                raise ValueError(
                    f"main_domain '{self.main_domain}' does not appear in content_markdown"
                )
        return self


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def seed_from_dict(data: dict[str, Any], *, strict: bool = True) -> SeedPayload:
    """Build a :class:`SeedPayload` from a raw dict, raising on invalid data.

    Wraps Pydantic's validation error into a :class:`ValueError` when
    *strict* is ``True``; otherwise returns a best-effort instance with
    partial data.

    Raises:
        ValueError: When *strict* is ``True`` and validation fails.
    """
    try:
        return SeedPayload(**data)
    except Exception as exc:
        if strict:
            raise ValueError(str(exc)) from exc
        return SeedPayload(**{k: v for k, v in data.items() if k in SeedPayload.model_fields})  # type: ignore[call-arg]


def plan_from_dict(data: dict[str, Any], *, strict: bool = True) -> PlannedPayload:
    """Build a :class:`PlannedPayload` from a raw dict, raising on invalid data.

    Raises:
        ValueError: When *strict* is ``True`` and validation fails.
    """
    try:
        return PlannedPayload(**data)
    except Exception as exc:
        if strict:
            raise ValueError(str(exc)) from exc
        return PlannedPayload(**{k: v for k, v in data.items() if k in PlannedPayload.model_fields})  # type: ignore[call-arg]
