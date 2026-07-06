"""Config-parser + helper tests for image-gen — route tests removed in U8 5b.

The /settings/test-image-gen and /settings/generate-sample-image route tests were
removed in U8 5b (Plan 2026-06-18-002) — those routes are retired. Coverage of the
same logic at /api/v1/settings/image-gen/* lives in test_webui_api_v1_image_gen.py.
"""
from __future__ import annotations

__tier__ = "unit"

import pytest

# Route tests for /settings/test-image-gen + /settings/generate-sample-image
# removed in U8 5b (Plan 2026-06-18-002) — those routes are retired.
# Equivalent coverage at /api/v1/settings/image-gen/* in test_webui_api_v1_image_gen.py.


# ── Config parser: provider field ────────────────────────────────────────────


def test_config_parser_rejects_unknown_provider(tmp_path, monkeypatch):
    """Invalid provider value raises InputValidationError."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        '[image_gen]\n'
        'base_url = "https://example.com"\n'
        'model = "m1"\n'
        'provider = "unknown_provider"\n'
    )
    from backlink_publisher._util.errors import InputValidationError
    from backlink_publisher.config import load_config
    with pytest.raises((InputValidationError, Exception)):
        load_config()


def test_config_parser_frw_requires_template_id(tmp_path, monkeypatch):
    """provider='frw' without frw_template_id raises InputValidationError."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        '[image_gen]\n'
        'base_url = "https://frw-dreamaiai-api.aiaiartist.com"\n'
        'model = "sdxl"\n'
        'provider = "frw"\n'
        '# frw_template_id intentionally omitted\n'
    )
    from backlink_publisher._util.errors import InputValidationError
    from backlink_publisher.config import load_config
    with pytest.raises((InputValidationError, Exception)):
        load_config()


def test_config_parser_frw_full_valid(tmp_path, monkeypatch):
    """provider='frw' with all required fields parses correctly."""
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        '[image_gen]\n'
        'base_url = "https://frw-dreamaiai-api.aiaiartist.com"\n'
        'model = "sdxl"\n'
        'provider = "frw"\n'
        'frw_template_id = "tpl_123"\n'
    )
    from backlink_publisher.config import load_config
    cfg = load_config()
    assert cfg.image_gen is not None
    assert cfg.image_gen.provider == "frw"
    assert cfg.image_gen.frw_template_id == "tpl_123"


# ── _image_gen_status helper ─────────────────────────────────────────────────


def test_image_gen_status_helper_reports_token_presence(tmp_path, monkeypatch):
    from backlink_publisher.config import load_config
    from webui_app.helpers.contexts import _image_gen_status

    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))

    cfg = load_config()
    status = _image_gen_status(cfg)
    assert status["configured"] is False
    assert status["token_present"] is False

    from backlink_publisher._util.secrets import write_frw_token
    write_frw_token("sk_x")

    status = _image_gen_status(cfg)
    assert status["token_present"] is True
    assert status["token_mtime"]  # non-empty timestamp string
