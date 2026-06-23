"""Core publish-workbench endpoints for ``/api/v1`` — Plan 2026-06-18-002 U5.

The four-stage single-publish workbench (plan → validate → preview → publish)
plus single-article body regeneration, as a versioned JSON surface the Vue SPA
consumes. These are **additive** (strangler-fig): the legacy ``/ce:*`` Jinja
routes are untouched and keep their own session-threaded flow until U8.

Two deliberate differences from the legacy routes:

* **Stateless.** The legacy ``/ce:*`` routes thread ``plans``/``validated``
  through the Flask ``session``; these endpoints take every input in the request
  body and return the rows, so the SPA owns stage state (Pinia). One call, one
  contract — no hidden cross-request state.
* **Real status codes + problem+json.** Failures raise :class:`ApiProblem`
  (RFC 9457) with the HTTP status mapped from the CLI ``exit_code``, instead of
  the legacy all-HTTP-200 re-render. Partial publish success is still 200 (the
  per-row outcomes live in ``results``; the SPA branches on ``state``).

Behaviour parity is preserved by calling the *same* ``PipelineAPI`` /
``build_generate_seed`` / ``publish_state_summary`` / history helpers the legacy
routes use — the seed shape, validation, publish summary and history side-effects
are a single source of truth, not a reimplementation.

Publish has no pollable task-id: the backend publish path is synchronous (300s
timeout) and adding a background task store would change the credential-holding
publish flow — judged high-risk and deferred (Open Questions / R-table). The SPA
renders a busy-state and back-fills on completion; it disables the submit control
while in flight so a double-submit can't race the ``dedup.db`` single-flight.
"""

from __future__ import annotations

import json
from typing import Any

from flask import jsonify, request

from backlink_publisher._util.markdown import render_to_html

from backlink_publisher.sdk.api import PipelineAPI, publish_state_summary
from ...helpers.cli_runner import surface_cli_error
from ...helpers.contexts import _get_velog_status
from ...helpers.history import _push_history_per_row, _push_history_single_failure
from ...helpers.url_meta import fetch_full_tdk, get_main_domain
from ...services.pipeline_service import build_generate_seed
from . import bp
from .errors import ApiProblem, from_pipe_result

_api = PipelineAPI()

# CLI exit_code → HTTP status. 1 = conflict/force-manifest (usage error),
# 2 = input/validation, 3 = auth/credential,
# 4 = upstream/external (also publish partial, handled before this is consulted).
_EXIT_STATUS = {1: 422, 2: 422, 3: 401, 4: 502}


def _status_for(result: Any) -> int:
    return _EXIT_STATUS.get(getattr(result, "exit_code", None), 502)


def _require_urls(data: dict[str, Any]) -> list[str]:
    urls = data.get("urls")
    if not isinstance(urls, list) or not urls:
        raise ApiProblem(
            422,
            "Missing URLs",
            detail="`urls` must be a non-empty array.",
            error_class="invalid_request",
        )
    return urls


def _plans_to_jsonl(plans: Any) -> str:
    """Accept either a JSONL string or an array of row objects → JSONL string."""
    if isinstance(plans, str):
        return plans
    if isinstance(plans, list):
        return "\n".join(json.dumps(r, ensure_ascii=False) for r in plans)
    return ""


# ── plan / generate ──────────────────────────────────────────────────────────


@bp.post("/pipeline/plan")
def pipeline_plan():
    """Generate article plans for the given URLs (the legacy ``/ce:generate``)."""
    data = request.get_json(silent=True) or {}
    urls = _require_urls(data)

    fetch_tdk = data.get("fetch_tdk", "no")
    tdk_data = fetch_full_tdk(urls[0]) if fetch_tdk == "yes" else {}
    seed = build_generate_seed(
        urls=urls,
        platform=data.get("platform", "blogger"),
        url_mode=data.get("url_mode", "C"),
        publish_mode=data.get("publish_mode", "publish"),
        target_language=data.get("target_language", "zh-CN"),
        custom_title=(data.get("custom_title") or "").strip(),
        custom_tags=(data.get("custom_tags") or "").strip(),
        tdk_data=tdk_data,
    )

    result = _api.plan(json.dumps(seed, ensure_ascii=False))
    if not result.success:
        raise from_pipe_result(result, status=_status_for(result))
    rows = result.rows
    if not rows:
        raise ApiProblem(
            502,
            "Generation produced no output",
            detail=result.stderr_cleaned or None,
            error_class="empty_output",
        )
    return jsonify({"plans": rows})


@bp.post("/pipeline/preview")
def pipeline_preview():
    """Single-article preview — plan one seed and return the first row.

    Mirrors the legacy ``/ce:preview`` seed shape, but returns the structured
    plan row (the SPA renders it) instead of raw markdown/HTML text.
    """
    data = request.get_json(silent=True) or {}
    urls = _require_urls(data)

    seed: dict[str, Any] = {
        "target_url": urls[0],
        "main_domain": get_main_domain(urls[0]),
        "platform": data.get("platform", "blogger"),
        "language": data.get("target_language", "zh-CN"),
        "url_mode": data.get("url_mode", "C"),
        "publish_mode": data.get("publish_mode", "publish"),
        "custom_title": data.get("custom_title", ""),
        "custom_tags": data.get("custom_tags", ""),
        "extra_urls": urls[1:],
    }
    if data.get("fetch_tdk") == "yes":
        seed["tdk"] = fetch_full_tdk(urls[0])

    result = _api.plan(json.dumps([seed], ensure_ascii=False))
    if not result.success:
        raise from_pipe_result(result, status=_status_for(result))
    rows = result.rows
    return jsonify({"plan": rows[0] if rows else None})


# ── validate ───────────────────────────────────────────────────────────────


@bp.post("/pipeline/validate")
def pipeline_validate():
    """Validate plan rows (URL checks skipped, mirroring ``/ce:validate``)."""
    data = request.get_json(silent=True) or {}
    if "plans" not in data:
        raise ApiProblem(
            422, "Missing plans", detail="`plans` is required.", error_class="invalid_request"
        )

    result = _api.validate(_plans_to_jsonl(data.get("plans")), no_check_urls=True)
    if not result.success:
        raise from_pipe_result(result, status=_status_for(result))
    return jsonify({"validated": result.rows})


# ── publish ──────────────────────────────────────────────────────────────────


@bp.post("/pipeline/publish")
def pipeline_publish():
    """Publish validated rows to a platform. Synchronous; partial success → 200.

    History side-effects (per-row / single-failure) match the legacy route so the
    publish-history store stays consistent across the two stacks during migration.
    """
    data = request.get_json(silent=True) or {}
    if "plans" not in data:
        raise ApiProblem(
            422, "Missing plans", detail="`plans` is required.", error_class="invalid_request"
        )
    platform = data.get("platform")
    if not platform:
        raise ApiProblem(
            422, "Missing platform", detail="`platform` is required.", error_class="invalid_request"
        )

    publish_mode = data.get("publish_mode", "publish")
    tier_1 = bool(data.get("tier_1", False))
    # Stateless API: the SPA may pass an optional target_url hint to enrich history
    # on total failure (per-row success carries its own URL).
    target_url = data.get("target_url") or "unknown"
    language = data.get("target_language", "zh-CN")
    plans_jsonl = _plans_to_jsonl(data.get("plans"))

    if platform == "velog":
        velog_status = _get_velog_status()
        if velog_status.get("state") not in ("ok", "fresh"):
            detail = velog_status.get("guide") or velog_status.get("label") or ""
            raise ApiProblem(
                400,
                "Velog credentials invalid",
                detail=f"请先在设置页重新绑定 Velog 凭证。{detail}".strip(),
                error_class="velog_credentials_invalid",
            )

    result = _api.publish(plans_jsonl, platform, publish_mode, tier_1=tier_1)

    if not result.success:
        msg = result.error or "发布失败"
        display = (
            f"[{result.error_class}] {msg}"
            if result.error_class and result.error_class != "unrecognized"
            else msg
        )
        _push_history_single_failure(
            target_url=target_url, platform=platform, language=language, error=display
        )
        raise from_pipe_result(result, status=_status_for(result))

    publish_results = result.rows
    if not publish_results:
        diagnostic = surface_cli_error(result.stderr) or "publish-backlinks returned no parseable rows"
        _push_history_single_failure(
            target_url=target_url, platform=platform, language=language, error=diagnostic
        )
        raise ApiProblem(
            502, "Publish produced no result rows", detail=diagnostic, error_class="empty_output"
        )

    _push_history_per_row(
        publish_results,
        target_url_fallback=target_url,
        platform_fallback=platform,
        language_fallback=language,
    )
    summary = publish_state_summary(publish_results)
    return jsonify(
        {
            "state": summary["state"],
            "n_ok": summary["n_ok"],
            "n_total": len(publish_results),
            "failure_detail": summary["failure_detail"],
            "results": publish_results,
        }
    )


# ── regen-body ─────────────────────────────────────────────────────────────


@bp.post("/pipeline/regen-body")
def pipeline_regen_body():
    """Re-generate one article body via the configured LLM (legacy ``/ce:regen-body``)."""
    data = request.get_json(silent=True) or {}
    main_domain = (data.get("main_domain") or "").strip()
    anchors = data.get("anchors") or []
    language = (data.get("language") or "").strip()
    topic = data.get("topic") or None

    if not main_domain or not isinstance(anchors, list):
        raise ApiProblem(
            422,
            "Invalid request",
            detail="main_domain and anchors are required",
            error_class="invalid_request",
        )

    from backlink_publisher.config import load_config

    try:
        cfg = load_config()
    except Exception as exc:  # noqa: BLE001
        raise ApiProblem(
            422, "Config load failed", detail=str(exc), error_class="invalid_request"
        ) from exc

    if not cfg.llm_anchor_provider or not cfg.llm_anchor_provider.use_article_gen:
        raise ApiProblem(
            400,
            "LLM not configured",
            detail="no LLM provider configured or article generation disabled",
            error_class="llm_not_configured",
        )

    from backlink_publisher.cli.plan_backlinks._templates import _domain_label_of

    domain_label = _domain_label_of(main_domain)
    try:
        from backlink_publisher.publishing.adapters.llm_anchor_provider import (
            OpenAICompatibleProvider,
        )

        provider = OpenAICompatibleProvider(
            base_url=cfg.llm_anchor_provider.base_url,
            api_key=cfg.llm_anchor_provider.api_key,
            model=cfg.llm_anchor_provider.model,
            temperature=cfg.llm_anchor_provider.temperature,
            system_prompt=cfg.llm_anchor_provider.system_prompt,
            article_system_prompt=cfg.llm_anchor_provider.article_system_prompt,
        )
        body = provider.generate_article_body(
            domain_label=domain_label,
            main_domain=main_domain,
            anchors=anchors,
            topic=topic,
            language=language,
        )
    except Exception as exc:  # noqa: BLE001
        from backlink_publisher.llm.client import _redact_for_log

        raise ApiProblem(
            502, "LLM call failed", detail=_redact_for_log(str(exc)), error_class="llm_call_failed"
        ) from exc

    return jsonify(
        {
            "content_markdown": body,
            "content_html": render_to_html(body),
            "content_source": "llm",
        }
    )
