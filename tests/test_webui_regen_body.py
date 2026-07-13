"""Unit tests for POST /ce:regen-body (Unit 4 of plan 2026-06-04-003)."""
from __future__ import annotations

__tier__ = "unit"
import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def client(disable_csrf):
    return disable_csrf.test_client()


def _post(client, payload):
    return client.post(
        '/ce:regen-body',
        data=json.dumps(payload),
        content_type='application/json',
    )


# ── 400 paths ───────────────────────────────────────────────────────────────

def test_bad_request_missing_main_domain(client):
    resp = _post(client, {'anchors': ['text'], 'language': 'zh-CN'})
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert data['error'] == 'bad_request'


def test_bad_request_anchors_not_list(client):
    resp = _post(client, {'main_domain': 'https://example.com', 'anchors': 'not-a-list', 'language': 'zh-CN'})
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert data['error'] == 'bad_request'


def test_llm_not_configured_no_provider(client, tmp_path, monkeypatch):
    monkeypatch.setenv('BACKLINK_PUBLISHER_CONFIG_DIR', str(tmp_path))
    resp = _post(client, {'main_domain': 'https://example.com', 'anchors': [], 'language': 'zh-CN'})
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert data['error'] == 'llm_not_configured'


def test_llm_not_configured_use_article_gen_false(client):
    cfg_mock = MagicMock()
    cfg_mock.llm_anchor_provider = MagicMock()
    cfg_mock.llm_anchor_provider.use_article_gen = False
    with patch('backlink_publisher.config.load_config', return_value=cfg_mock):
        resp = _post(client, {'main_domain': 'https://example.com', 'anchors': [], 'language': 'zh-CN'})
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert data['error'] == 'llm_not_configured'
    assert 'use_article_gen' in data.get('detail', '')


# ── 200 happy path ────────────────────────────────────────────────────────

def test_happy_path_returns_content(client):
    cfg_mock = MagicMock()
    cfg_mock.llm_anchor_provider = MagicMock()
    cfg_mock.llm_anchor_provider.use_article_gen = True
    cfg_mock.llm_anchor_provider.base_url = 'https://api.test/v1'
    cfg_mock.llm_anchor_provider.api_key = 'sk-test-secret'
    cfg_mock.llm_anchor_provider.model = 'gpt-4o-mini'
    cfg_mock.llm_anchor_provider.temperature = 0.7
    cfg_mock.llm_anchor_provider.system_prompt = ''
    cfg_mock.llm_anchor_provider.article_system_prompt = ''

    provider_mock = MagicMock()
    provider_mock.generate_article_body.return_value = '# Test\n\nBody text.'

    with patch('backlink_publisher.config.load_config', return_value=cfg_mock), \
         patch('backlink_publisher.publishing.adapters.llm_anchor_provider.OpenAICompatibleProvider',
               return_value=provider_mock):
        resp = _post(client, {
            'main_domain': 'https://51acgs.com',
            'anchors': ['anchor text'],
            'language': 'zh-CN',
            'topic': None,
        })

    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['content_source'] == 'llm'
    assert data['content_markdown'] == '# Test\n\nBody text.'
    assert data['content_html']  # non-empty server-rendered HTML
    assert '<h1' in data['content_html'] or 'Test' in data['content_html']


# ── XSS: content_html must be sanitized (audit [26][27]) ────────────────────

def test_regen_body_sanitizes_raw_llm_html_in_content_html(client):
    """content_html is assigned to profiles.js `preview.innerHTML`, so raw LLM
    HTML (event-handler payloads) must be escaped, not passed through verbatim."""
    cfg_mock = MagicMock()
    cfg_mock.llm_anchor_provider = MagicMock()
    cfg_mock.llm_anchor_provider.use_article_gen = True
    cfg_mock.llm_anchor_provider.base_url = 'https://api.test/v1'
    cfg_mock.llm_anchor_provider.api_key = 'sk-test-secret'
    cfg_mock.llm_anchor_provider.model = 'gpt-4o-mini'
    cfg_mock.llm_anchor_provider.temperature = 0.7
    cfg_mock.llm_anchor_provider.system_prompt = ''
    cfg_mock.llm_anchor_provider.article_system_prompt = ''

    provider_mock = MagicMock()
    provider_mock.generate_article_body.return_value = (
        'Hello <img src=x onerror=alert(1)> <script>alert(2)</script>'
    )

    with patch('backlink_publisher.config.load_config', return_value=cfg_mock), \
         patch('backlink_publisher.publishing.adapters.llm_anchor_provider.OpenAICompatibleProvider',
               return_value=provider_mock):
        resp = _post(client, {
            'main_domain': 'https://51acgs.com', 'anchors': [], 'language': 'zh-CN',
        })

    assert resp.status_code == 200
    html = json.loads(resp.data)['content_html']
    assert '<script>' not in html
    assert '<img' not in html  # raw event-handler element escaped, not live
    assert 'Hello' in html     # markdown still rendered, text preserved


def test_render_markdown_safe_filter_is_registered_and_escapes(disable_csrf):
    """The admin plan preview (_tab_new.html) uses this filter (audit [26])."""
    filt = disable_csrf.jinja_env.filters.get('render_markdown_safe')
    assert filt is not None, "render_markdown_safe Jinja filter must be registered"
    out = filt('x <script>alert(1)</script>')
    assert '<script>' not in out


# ── 502 path ─────────────────────────────────────────────────────────────

def test_llm_call_failed_redacts_api_key(client):
    cfg_mock = MagicMock()
    cfg_mock.llm_anchor_provider = MagicMock()
    cfg_mock.llm_anchor_provider.use_article_gen = True
    cfg_mock.llm_anchor_provider.base_url = 'https://api.test/v1'
    cfg_mock.llm_anchor_provider.api_key = 'sk-test-secret'
    cfg_mock.llm_anchor_provider.model = 'gpt-4o-mini'
    cfg_mock.llm_anchor_provider.temperature = 0.7
    cfg_mock.llm_anchor_provider.system_prompt = ''
    cfg_mock.llm_anchor_provider.article_system_prompt = ''

    def _raise(*args, **kwargs):
        raise RuntimeError('auth failed Bearer sk-test-secret for endpoint')

    provider_mock = MagicMock()
    provider_mock.generate_article_body.side_effect = _raise

    with patch('backlink_publisher.config.load_config', return_value=cfg_mock), \
         patch('backlink_publisher.publishing.adapters.llm_anchor_provider.OpenAICompatibleProvider',
               return_value=provider_mock):
        resp = _post(client, {
            'main_domain': 'https://51acgs.com',
            'anchors': [],
            'language': 'zh-CN',
        })

    assert resp.status_code == 502
    data = json.loads(resp.data)
    assert data['error'] == 'llm_call_failed'
    assert 'sk-test-secret' not in data.get('detail', '')
