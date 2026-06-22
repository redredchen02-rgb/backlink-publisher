"""Plan E-perf — _g_cache per-request memoization tests."""
from __future__ import annotations

__tier__ = "unit"
import ast
import inspect
import pytest

from webui_app import create_app
from webui_app.helpers._request_cache import _g_cache


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    app = create_app()
    app.config["TESTING"] = True
    app.config["CSRF_ENABLED"] = False
    return app


# ── _g_cache unit tests ───────────────────────────────────────────────────────

def test_g_cache_returns_fn_result_outside_request_context():
    """Outside a request context, _g_cache calls fn() and returns its result."""
    calls = []
    def fn():
        calls.append(1)
        return 42
    result = _g_cache('test_key', fn)
    assert result == 42
    assert len(calls) == 1


def test_g_cache_calls_fn_each_time_outside_request_context():
    """Outside request context there is no g, so fn() is called every time."""
    calls = []
    def fn():
        calls.append(1)
        return 99
    _g_cache('k', fn)
    _g_cache('k', fn)
    assert len(calls) == 2  # no caching outside request context


def test_g_cache_returns_cached_value_within_request(app):
    """Within a request context, _g_cache returns the same value for the same key."""
    calls = []
    def fn():
        calls.append(1)
        return {'result': 'loaded'}

    with app.test_request_context('/'):
        first = _g_cache('my_key', fn)
        second = _g_cache('my_key', fn)

    assert first == second == {'result': 'loaded'}
    assert len(calls) == 1  # fn() called only once despite two cache hits


def test_g_cache_different_keys_call_fn_independently(app):
    """Different keys do not share cached values."""
    calls = {}
    def make_fn(name):
        def fn():
            calls[name] = calls.get(name, 0) + 1
            return name
        return fn

    with app.test_request_context('/'):
        r1 = _g_cache('key_a', make_fn('a'))
        r2 = _g_cache('key_b', make_fn('b'))
        r3 = _g_cache('key_a', make_fn('a'))  # cache hit

    assert r1 == 'a'
    assert r2 == 'b'
    assert r3 == 'a'
    assert calls == {'a': 1, 'b': 1}  # key_a fn called once, key_b fn called once


def test_g_cache_cleared_between_requests(app):
    """Each new request context gets a fresh cache — no cross-request pollution."""
    calls = []
    def fn():
        calls.append(1)
        return object()  # unique per call

    with app.test_request_context('/'):
        v1 = _g_cache('cfg', fn)

    with app.test_request_context('/'):
        v2 = _g_cache('cfg', fn)

    assert len(calls) == 2  # fn() called once per request, not once total
    assert v1 is not v2     # different objects — cache was cleared


# ── Integration: load_config() called once per /settings request ─────────────

def test_load_config_called_once_per_settings_request(app, monkeypatch):
    """_settings_context + channel_probes call load_config() but hit disk only once."""
    from backlink_publisher import config as _cfg_mod
    original = _cfg_mod.load_config
    calls = []

    def counting_load_config():
        calls.append(1)
        return original()

    monkeypatch.setattr(_cfg_mod, 'load_config', counting_load_config)
    # Also patch at the consumer references
    import webui_app.helpers.contexts as ctx_mod
    import webui_app.helpers.channel_probes as probe_mod
    monkeypatch.setattr(ctx_mod, 'load_config', counting_load_config)
    monkeypatch.setattr(probe_mod, 'load_config', counting_load_config)

    with app.test_client() as client:
        resp = client.get('/settings')
        assert resp.status_code == 200

    # With flask.g caching, load_config() should be called exactly once
    # despite _settings_context + _get_velog_status + _get_blogger_token_status
    # all needing the config.
    assert len(calls) == 1, (
        f"load_config() called {len(calls)} times in one /settings request; "
        f"expected 1 (flask.g cache should deduplicate)"
    )


# ── Integration: load_config() called once per /sites request ────────────────

def test_load_config_called_once_per_sites_request(app, monkeypatch):
    """sites_form (GET /sites) must call load_config() at most once per request."""
    from backlink_publisher import config as _cfg_mod
    original = _cfg_mod.load_config
    calls = []

    def counting_load_config():
        calls.append(1)
        return original()

    monkeypatch.setattr(_cfg_mod, 'load_config', counting_load_config)
    import webui_app.helpers.contexts as ctx_mod
    import webui_app.helpers.channel_probes as probe_mod
    import webui_app.routes.sites as sites_mod
    monkeypatch.setattr(ctx_mod, 'load_config', counting_load_config)
    monkeypatch.setattr(probe_mod, 'load_config', counting_load_config)
    monkeypatch.setattr(sites_mod, 'load_config', counting_load_config)

    with app.test_client() as client:
        resp = client.get('/sites')
        assert resp.status_code == 200

    assert len(calls) <= 1, (
        f"load_config() called {len(calls)} times in one GET /sites request; "
        f"expected at most 1 (flask.g cache should deduplicate)"
    )


# ── AST enforcement: write-handler functions must not use _g_cache('config') ──

def _get_function_source(module, func_name: str) -> str | None:
    """Return source of a named function from a module, or None if not found."""
    fn = getattr(module, func_name, None)
    if fn is None:
        return None
    try:
        return inspect.getsource(fn)
    except (OSError, TypeError):
        return None


_WRITE_HANDLER_SPECS = [
    # (module_dotted_path, function_name)
    ("webui_app.routes.settings_basic", "settings_save_target_keywords"),
    # settings_{save,clear}_medium_token removed in U8 (Medium integration tokens retired).
    ("webui_app.routes.settings_basic", "settings_revoke_blogger"),
    ("webui_app.routes.sites", "sites_save_three_url"),
    ("webui_app.routes.oauth", "settings_save_blogger_oauth"),
    ("webui_app.routes.oauth", "settings_blogger_oauth_start"),
    ("webui_app.routes.oauth", "settings_blogger_oauth_callback"),
    ("webui_app.routes.llm", "_sync_image_gen_config"),
    ("webui_app.routes.token_paste", "save_channel_token"),
    ("webui_app.routes.token_paste", "save_notion_channel_token"),
    ("webui_app.routes.channel_bind_save", "_save_token"),
    ("webui_app.routes.channel_bind_save", "_save_token_fields"),
    ("webui_app.routes.channel_bind_save", "_save_paste_blob"),
    ("webui_app.routes.channel_bind_save", "_save_userpass"),
]


@pytest.mark.parametrize("module_path,func_name", _WRITE_HANDLER_SPECS)
def test_write_handler_does_not_use_g_cache_for_config(module_path: str, func_name: str):
    """Write-handler functions must keep load_config() as a direct call.

    _g_cache('config', load_config) must NOT appear in these functions — they
    perform disk writes using the config object and require a fresh load, not a
    request-scoped cached version.
    """
    import importlib
    try:
        mod = importlib.import_module(module_path)
    except ImportError:
        pytest.skip(f"module {module_path!r} not importable")

    source = _get_function_source(mod, func_name)
    if source is None:
        pytest.skip(f"{module_path}.{func_name} not found (may have been renamed)")

    assert "_g_cache('config'" not in source and '_g_cache("config"' not in source, (
        f"{module_path}.{func_name} is a write-handler but contains _g_cache('config', ...). "
        f"Write-handlers must use direct load_config() calls to avoid stale-config writes. "
        f"Remove the _g_cache call and use load_config() directly."
    )
