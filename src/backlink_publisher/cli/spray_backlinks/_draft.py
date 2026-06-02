"""Unit 3 — per-shot LLM body rewrite + publish-ready row assembly.

This is the **single LLM boundary** for spray-backlinks. The publish path stays
LLM-free; ``plan_rows`` is called with its provider neutered so the only LLM
call site is here (per the no-runtime-LLM authorized-exception model — see
``docs/solutions/best-practices/no-runtime-llm-2026-05-15.md`` and the plan).

Each shot's body is genuinely rewritten per platform (distinct phrasing/angle)
so the N posts are not near-duplicates — the actual stealth mechanism. Anchors
and links come from ``plan_rows``' static path (deterministic; no LLM anchor
fallback because the provider is neutered).
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Callable
from typing import Any

from backlink_publisher._util.errors import DependencyError

# Signature: (platform, shot_idx, domain_label, main_domain, anchors, topic,
# language) -> rewritten markdown body. Injectable so tests never hit network.
RewriteFn = Callable[[str, int, str, str, list[str], str | None, str], str]


class LLMNotConfiguredError(DependencyError):
    """Raised when the LLM provider/key is absent. Operator-facing, exit 3.

    R4a: the rewrite must NOT silently fall back to identical content — absence
    of a key is a hard, clear error, not a degrade.
    """


def _salt_id(base_id: str, platform: str, shot_idx: int) -> str:
    """Re-salt the payload id so re-runs / same-target shots stay distinct in
    the dedup gate (the base id hashes target:domain:url_mode:platform only)."""
    digest = hashlib.sha256(f"{base_id}:{platform}:{shot_idx}".encode()).hexdigest()
    return digest[:16]


def _default_rewrite_fn(cfg: Any) -> RewriteFn:
    """Build the production LLM rewrite function from config.

    Raises :class:`LLMNotConfiguredError` immediately if no provider is
    configured (R4a hard abort — no identical-content fallback).
    """
    provider_cfg = getattr(cfg, "llm_anchor_provider", None)
    if provider_cfg is None:
        raise LLMNotConfiguredError(
            "spray-backlinks requires an LLM provider for per-platform rewrite; "
            "none configured. Set [llm.anchor_provider] (or the WebUI "
            "llm-settings.json sidecar). The verb does NOT fall back to identical "
            "content."
        )  # exit_code 3 inherited from DependencyError

    def _rewrite(
        platform: str,
        shot_idx: int,
        domain_label: str,
        main_domain: str,
        anchors: list[str],
        topic: str | None,
        language: str,
    ) -> str:
        from backlink_publisher.publishing.adapters.llm_anchor_provider import (
            OpenAICompatibleProvider,
        )

        # Per-platform variation directive drives genuinely distinct bodies.
        variation = (
            f"\n\n[Variation directive] Produce a DISTINCT version for platform "
            f"'{platform}' (variant #{shot_idx}). Use different opening, sentence "
            f"structure, section order, and phrasing from any other variant. Keep "
            f"the same facts, anchors, and target — only the surface form differs."
        )
        provider = OpenAICompatibleProvider(
            base_url=provider_cfg.base_url,
            api_key=provider_cfg.api_key,
            model=provider_cfg.model,
            temperature=provider_cfg.temperature,
            system_prompt=provider_cfg.system_prompt,
            article_system_prompt=(provider_cfg.article_system_prompt or "") + variation,
        )
        return provider.generate_article_body(
            domain_label=domain_label,
            main_domain=main_domain,
            anchors=anchors,
            topic=topic,
            language=language,
        )

    return _rewrite


def draft_row(
    seed: dict[str, Any],
    platform: str,
    shot_idx: int,
    cfg: Any,
    *,
    rewrite_fn: RewriteFn,
    fetch_verify_enabled: bool = True,
) -> dict[str, Any]:
    """Build one publish-ready row: static skeleton from ``plan_rows`` (LLM
    neutered) + an LLM-rewritten body + a salted id. Validates before returning.

    Raises :class:`InputValidationError`-family on a skeleton/validation failure.
    """
    from backlink_publisher.cli.plan_backlinks._engine import plan_rows
    from backlink_publisher.cli.plan_backlinks._payload import _resolve_article_anchors
    from backlink_publisher.cli.plan_backlinks._templates import _domain_label_of
    from backlink_publisher._util.errors import InputValidationError
    from backlink_publisher.schema import validate_publish_payload

    # Neuter the provider so plan_rows takes its static (no-LLM) path — the only
    # LLM call is the body rewrite below.
    cfg_no_llm = dataclasses.replace(cfg, llm_anchor_provider=None)
    outcome = plan_rows(
        [dict(seed)], cfg_no_llm, fetch_verify_enabled=fetch_verify_enabled
    )
    if outcome.errors or not outcome.outputs:
        raise InputValidationError(
            f"spray-backlinks: skeleton generation failed for {platform}: "
            + "; ".join(outcome.errors or ["no output"])
        )
    row = outcome.outputs[0]

    main_domain = str(seed.get("main_domain", "")).rstrip("/")
    url_mode = seed.get("url_mode", "A")
    domain_label = _domain_label_of(main_domain)
    anchors = _resolve_article_anchors(cfg_no_llm, main_domain, url_mode, domain_label)
    topic = seed.get("topic")
    language = seed.get("target_language") or seed.get("language", "zh-CN")

    body = rewrite_fn(
        platform, shot_idx, domain_label, main_domain, list(anchors), topic, language
    )
    if not isinstance(body, str) or not body.strip():
        raise InputValidationError(
            f"spray-backlinks: empty LLM body for {platform} (variant #{shot_idx})"
        )

    # The LLM owns the prose (distinctness/stealth); the canonical link block is
    # appended verbatim from the deterministic skeleton so the required backlinks
    # (main_domain/target) are present and exact — validate_publish_payload
    # enforces that the main_domain URL appears in content_markdown.
    from backlink_publisher._util.markdown import links_to_markdown

    links_md = links_to_markdown(row.get("links", []))
    row["content_markdown"] = body.rstrip() + "\n\n" + links_md
    row.pop("content_html", None)
    row["id"] = _salt_id(str(row.get("id", "")), platform, shot_idx)

    errors = validate_publish_payload(row)
    if errors:
        raise InputValidationError(
            f"spray-backlinks: drafted row invalid for {platform}: "
            + "; ".join(errors)
        )
    return row
