"""/ce:batch + /ce:publish-real — Plan Unit 3.

Phase A refactoring: uses ``PipelineAPI`` for all CLI invocations.
"""

from __future__ import annotations

import json
from typing import Any

from flask import Blueprint, current_app, request, session

from backlink_publisher.config import load_config as _load_cfg

from ..api import PipelineAPI
from ..helpers.contexts import _render
from ..helpers.history import (
    _push_history_per_row,
    _push_history_single_failure,
)
from ..helpers.security import _check_bind_origin_or_abort
from ..helpers.url_meta import get_main_domain

bp = Blueprint("batch", __name__)
_api = PipelineAPI()


@bp.before_request
def _enforce_bind_origin() -> None:
    if not current_app.config.get('CSRF_ENABLED', True):
        return
    if not current_app.config.get('WTF_CSRF_ENABLED', True):
        return
    _check_bind_origin_or_abort()


def _check_medium_setup() -> str | None:
    """Return error HTML if Medium not ready, None if OK."""
    from backlink_publisher.publishing._verify_setup import _check_medium_setup as _verify_medium

    try:
        err = _verify_medium(_load_cfg())
        if err:
            return (
                "❌ Medium 平台未配置完成。"
                "请前往 <a href='/settings' style='color:var(--primary);font-weight:600;'>"
                "设置 → Medium</a> 配置凭据。"
            )
    except Exception:
        return (
            "❌ Medium 平台设置检查失败。"
            "请前往 <a href='/settings' style='color:var(--primary);font-weight:600;'>"
            "设置 → Medium</a> 确认配置。"
        )
    return None


@bp.route('/ce:batch', methods=['POST'])
def ce_batch() -> Any:
    """Batch publish: process multiple target URLs through the full pipeline."""
    urls_text = request.form.get('batch_urls', '').strip()
    platform = request.form.get('platform', 'medium')
    # Plan 013 U2: converge field name to `target_language`; keep `language` as
    # backwards-compat fallback for any caller still using the old field name.
    language = (
        request.form.get('target_language')
        or request.form.get('language', 'zh-CN')
    )
    url_mode = request.form.get('url_mode', 'C')
    publish_mode = request.form.get('publish_mode', 'publish')

    raw_urls = [u.strip() for u in urls_text.split('\n') if u.strip()]
    if not raw_urls:
        return _render('index.html', error="请输入至少一个网址", batch_tab=True,
                       batch_urls=urls_text, config={})

    urls = []
    for u in raw_urls:
        if not u.startswith(('http://', 'https://')):
            u = 'https://' + u
        urls.append(u)

    if platform == 'medium':
        err = _check_medium_setup()
        if err:
            return _render('index.html', error=err, batch_tab=True,
                           batch_urls=urls_text, config={})

    seed_jsonl = '\n'.join(
        json.dumps({
            'target_url': u,
            'main_domain': get_main_domain(u),
            'platform': platform,
            'language': language,
            'url_mode': url_mode,
            'publish_mode': publish_mode,
        }, ensure_ascii=False)
        for u in urls
    )

    plan_res = _api.plan(seed_jsonl)
    if not plan_res.success:
        return _render('index.html', error=f"计划阶段失败: {plan_res.error}", batch_tab=True,
                       batch_urls=urls_text, config={})

    val_res = _api.validate(plan_res.stdout, no_check_urls=True)
    if not val_res.success:
        return _render('index.html', error=f"验证阶段失败: {val_res.error}", batch_tab=True,
                       batch_urls=urls_text, config={})

    pub_res = _api.publish(val_res.stdout, platform, publish_mode)
    publish_results = pub_res.rows

    result_by_url = {r.get('target_url', ''): r for r in publish_results}
    results = []
    for url in urls:
        r = result_by_url.get(url) or result_by_url.get(url.rstrip('/') + '/')
        if r and not r.get('error'):
            article_url = r.get('published_url') or r.get('draft_url', '')
            results.append({
                'url': url, 'status': 'success',
                'article_url': article_url or '',
                'title': r.get('title', ''),
            })
        elif r and r.get('error'):
            results.append({
                'url': url, 'status': 'failed', 'article_url': '',
                'title': r.get('title', ''), 'error': r.get('error', ''),
            })
        else:
            results.append({
                'url': url, 'status': 'failed', 'article_url': '',
                'title': '', 'error': pub_res.stderr_cleaned or 'no output',
            })

    # Plan 2026-05-19-006 Unit 1: per-row history with real status carried
    # forward (including `*_unverified` suffixes).
    if publish_results:
        _push_history_per_row(
            publish_results,
            target_url_fallback=urls[0] if urls else 'batch',
            platform_fallback=platform,
            language_fallback=language,
        )

    return _render('index.html', batch_results=results, batch_tab=True,
                   batch_urls=urls_text, config={})


@bp.route('/ce:publish-real', methods=['POST'])
def ce_publish_real() -> Any:
    """Real publish (mode=publish, not dry-run)."""
    validated = request.form.get('validated', '')
    platform = request.form.get('platform', 'medium')
    config = session.get('config', {})

    if platform == 'medium':
        err = _check_medium_setup()
        if err:
            return _render('index.html', error=err,
                           config=config, history_active=True)

    result = _api.publish(validated, platform, "publish")
    if not result.success:
        msg = result.error or "发布失败"
        history = _push_history_single_failure(
            target_url=config.get('target_url', 'unknown'),
            platform=platform,
            language=config.get('target_language', 'zh-CN'),
            error=msg,
        )
        return _render('index.html', error=f"发布失败: {msg}",
            config=config, history=history, history_active=True)

    published = result.stdout
    if not published.strip():
        return _render('index.html',
            error=result.stderr_cleaned or "发布失败",
            config=config, history_active=True)

    publish_results = result.rows
    # Plan 2026-05-19-006 Unit 1: per-row truth-propagation.
    history = _push_history_per_row(
        publish_results,
        target_url_fallback=config.get('target_url', 'unknown'),
        platform_fallback=platform,
        language_fallback=config.get('target_language', 'zh-CN'),
    )

    return _render('index.html', published=published,
        publish_results=publish_results, config=config,
        history=history, history_active=True)
