"""Publish routes (Wave 3 Unit 5 split).

Extracted from ``routes/pipeline.py`` (2026-06-11).  Contains:
  /ce:publish, /ce:publish-chain
``routes/__init__.py`` registers this blueprint alongside ``pipeline_plan.bp``.
"""
from __future__ import annotations

import json
from typing import Any

from flask import Blueprint, request, session

from backlink_publisher._util.logger import plan_logger

from ..api import PipelineAPI
from ..api.pipeline_api import publish_state_summary
from ..helpers.cli_runner import surface_cli_error
from ..helpers.contexts import _get_velog_status, _render
from ..helpers.history import (
    _push_history_per_row,
    _push_history_single_failure,
)
from ..helpers.url_meta import fetch_full_tdk
from ..services.pipeline_service import build_generate_seed

bp = Blueprint("pipeline_publish", __name__)
_api = PipelineAPI()


@bp.route('/ce:publish', methods=['POST'])
def ce_publish() -> Any:
    plans = session.get('plans', '') or request.form.get('plans', '')
    config = session.get('config', {})

    platform = request.form.get('platform', config.get('platform', 'medium'))
    publish_mode = request.form.get('publish_mode', config.get('publish_mode', 'publish'))
    tier_1 = request.form.get('tier_1') in ('1', 'true')
    target_url = config.get('target_url', 'unknown')
    language = config.get('target_language', 'zh-CN')

    if platform == 'velog':
        velog_status = _get_velog_status()
        if velog_status.get('state') not in ('ok', 'fresh'):
            detail = velog_status.get('guide') or velog_status.get('label') or ''
            return _render('index.html',
                error=f"Velog 凭证无效，请先在设置页重新绑定。{detail}",
                config=config, history_active=True)

    result = _api.publish(plans, platform, publish_mode, tier_1=tier_1)

    if not result.success:
        # ``result.error`` is the full typed message (or banner-stripped stderr on
        # QUARANTINE) — no truncation. Tag the typed class for the operator.
        msg = result.error or "发布失败"
        display = (
            f"[{result.error_class}] {msg}"
            if result.error_class and result.error_class != "unrecognized"
            else msg
        )
        _push_history_single_failure(
            target_url=target_url, platform=platform, language=language, error=display,
        )
        plan_logger.warn(
            "webui_publish_result",
            state="all_failed", platform=platform, publish_mode=publish_mode,
            n_ok=0, n_failed=0, error_class=result.error_class, stderr_preview=msg,
        )
        return _render('index.html',
            publish_state='all_failed', publish_error=f"发布失败: {display}",
            config=config, history_active=True)

    published = result.stdout
    stderr = result.stderr
    publish_results = result.rows

    if not publish_results:
        diagnostic = surface_cli_error(result.stderr) or "publish-backlinks returned no parseable rows"
        _push_history_single_failure(
            target_url=target_url, platform=platform, language=language,
            error=diagnostic,
        )
        plan_logger.warn(
            "webui_publish_result",
            state="all_failed", platform=platform, publish_mode=publish_mode,
            n_ok=0, n_failed=0, stderr_preview=diagnostic,
        )
        return _render('index.html',
            publish_state='all_failed', publish_error=diagnostic,
            published=published, config=config, history_active=True)

    _push_history_per_row(
        publish_results,
        target_url_fallback=target_url,
        platform_fallback=platform,
        language_fallback=language,
    )

    summary = publish_state_summary(publish_results)
    n_ok = summary["n_ok"]
    n_failed = summary["n_failed"]
    publish_state = summary["state"]
    publish_error = summary["failure_detail"]

    log_fn = plan_logger.info if publish_state == 'all_success' else plan_logger.warn
    log_fn(
        "webui_publish_result",
        state=publish_state, platform=platform, publish_mode=publish_mode,
        n_ok=n_ok, n_failed=n_failed, stderr_preview=surface_cli_error(stderr),
    )

    return _render('index.html', published=published,
                   publish_results=publish_results,
                   publish_state=publish_state, publish_error=publish_error,
                   n_ok=n_ok, n_total=len(publish_results),
                   config=config, history_active=True)


@bp.route('/ce:publish-chain', methods=['POST'])
def ce_publish_chain() -> Any:
    """One-click plan → validate → publish chain.

    Takes the same form data as ``/ce:generate`` (URLs, platform, language,
    etc.) plus the publish-mode override, and runs the full pipeline in a
    single request, rendering the final publish result page.
    """
    stored_config = session.get('config', {})
    urls_json = request.form.get('urls_json', session.get('urls_json', '[]'))

    try:
        urls = json.loads(urls_json)
    except Exception:
        urls = stored_config.get('urls', [])

    if not urls:
        return _render('index.html', error="没有有效的连结", config=stored_config)

    platform = request.form.get('platform', stored_config.get('platform', 'medium'))
    url_mode = request.form.get('url_mode', stored_config.get('url_mode', 'C'))
    publish_mode = request.form.get('publish_mode',
                                    stored_config.get('publish_mode', 'draft'))
    tier_1 = request.form.get('tier_1') in ('1', 'true')
    target_language = request.form.get('target_language',
                                       stored_config.get('target_language', 'zh-CN'))
    custom_title = request.form.get('custom_title', '').strip()
    custom_tags = request.form.get('custom_tags', '').strip()
    fetch_tdk = request.form.get('fetch_tdk', stored_config.get('fetch_tdk', 'no'))

    main_url = urls[0]

    if platform == 'velog':
        velog_status = _get_velog_status()
        if velog_status.get('state') not in ('ok', 'fresh'):
            return _render('index.html',
                error=f"Velog 凭证无效，请先在设置页重新绑定。{velog_status.get('guide', '')}",
                config=stored_config)

    tdk_data = {}
    if fetch_tdk == 'yes':
        tdk_data = fetch_full_tdk(main_url)

    seed = build_generate_seed(
        urls=urls,
        platform=platform,
        url_mode=url_mode,
        publish_mode=publish_mode,
        target_language=target_language,
        custom_title=custom_title,
        custom_tags=custom_tags,
        tdk_data=tdk_data,
    )
    result = _api.plan(json.dumps(seed, ensure_ascii=False))
    if not result.success:
        return _render('index.html', error=result.error or "生成失败", config=stored_config)

    plans = result.stdout
    if not plans.strip():
        return _render('index.html', error=result.stderr_cleaned or "生成失败，没有输出",
                       config=stored_config)

    validate_result = _api.validate(plans, no_check_urls=True)
    if not validate_result.success:
        return _render('index.html',
                       error=validate_result.error or "验证失败",
                       plans=plans, config=stored_config)

    validated = validate_result.stdout
    if not validated.strip():
        return _render('index.html',
                       error=validate_result.stderr_cleaned or "验证失败，没有输出",
                       plans=plans, config=stored_config)

    pub_result = _api.publish(validated, platform, publish_mode, tier_1=tier_1)
    if not pub_result.success:
        msg = pub_result.error or "发布失败"
        display = (
            f"[{pub_result.error_class}] {msg}"
            if pub_result.error_class and pub_result.error_class != "unrecognized"
            else msg
        )
        _push_history_single_failure(
            target_url=main_url, platform=platform,
            language=target_language, error=display,
        )
        return _render('index.html', plans=plans,
                       error=f"发布失败: {display}", config=stored_config)

    published = pub_result.stdout
    publish_results = pub_result.rows

    _push_history_per_row(
        publish_results,
        target_url_fallback=main_url,
        platform_fallback=platform,
        language_fallback=target_language,
    )

    summary = publish_state_summary(publish_results)
    n_ok = summary["n_ok"]
    n_total = len(publish_results)
    publish_state = summary["state"]
    publish_error = summary["failure_detail"]

    return _render('index.html', published=published,
                   publish_results=publish_results,
                   publish_state=publish_state, publish_error=publish_error,
                   n_ok=n_ok, n_total=n_total,
                   config=stored_config, history_active=True)
