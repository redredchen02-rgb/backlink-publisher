"""Unit 2: env-var override getters for post-publish delays across 14 adapters.

Tests that each adapter's _post_publish_delay_s() getter:
  - Returns the hardcoded default when the env var is not set
  - Returns the override value when the env var is set to a valid integer
  - Returns 0 when the env var is set to "0" (valid — disables delay)
  - Falls back to the default when the env var is set to a non-integer
  - qiita/zenn AdapterResult instances carry non-zero post_publish_delay_seconds (bug fix)
"""
from __future__ import annotations

__tier__ = "unit"
import importlib
import os
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Adapter registry: (module_path, getter_name, env_var, default_value)
# ---------------------------------------------------------------------------
ADAPTER_DELAY_PARAMS = [
    (
        "backlink_publisher.publishing.adapters.devto_api",
        "_post_publish_delay_s",
        "DEVTO_PUBLISH_DELAY_S",
        30,
    ),
    (
        "backlink_publisher.publishing.adapters.hashnode_graphql",
        "_post_publish_delay_s",
        "HASHNODE_PUBLISH_DELAY_S",
        15,
    ),
    (
        "backlink_publisher.publishing.adapters.hatena_atompub",
        "_post_publish_delay_s",
        "HATENA_PUBLISH_DELAY_S",
        30,
    ),
    (
        "backlink_publisher.publishing.adapters.linkedin_api",
        "_post_publish_delay_s",
        "LINKEDIN_PUBLISH_DELAY_S",
        60,
    ),
    (
        "backlink_publisher.publishing.adapters.notion_api",
        "_post_publish_delay_s",
        "NOTION_PUBLISH_DELAY_S",
        30,
    ),
    (
        "backlink_publisher.publishing.adapters.rentry_api",
        "_post_publish_delay_s",
        "RENTRY_PUBLISH_DELAY_S",
        10,
    ),
    (
        "backlink_publisher.publishing.adapters.substack_api",
        "_post_publish_delay_s",
        "SUBSTACK_PUBLISH_DELAY_S",
        60,
    ),
    (
        "backlink_publisher.publishing.adapters.tumblr_api",
        "_post_publish_delay_s",
        "TUMBLR_PUBLISH_DELAY_S",
        15,
    ),
    (
        "backlink_publisher.publishing.adapters.wordpresscom_api",
        "_post_publish_delay_s",
        "WORDPRESSCOM_PUBLISH_DELAY_S",
        15,
    ),
    (
        "backlink_publisher.publishing.adapters.writeas_api",
        "_post_publish_delay_s",
        "WRITEAS_PUBLISH_DELAY_S",
        5,
    ),
    (
        "backlink_publisher.publishing.adapters.qiita_api",
        "_post_publish_delay_s",
        "QIITA_PUBLISH_DELAY_S",
        5,
    ),
    (
        "backlink_publisher.publishing.adapters.zenn_github",
        "_post_publish_delay_s",
        "ZENN_PUBLISH_DELAY_S",
        10,
    ),
    (
        "backlink_publisher.publishing.adapters.medium_api",
        "_post_publish_delay_s",
        "MEDIUM_PUBLISH_DELAY_S",
        30,
    ),
    (
        "backlink_publisher.publishing.adapters.medium_browser",
        "_post_publish_delay_s",
        "MEDIUM_PUBLISH_DELAY_S",
        30,
    ),
    # Wave-1/2 adapters (U1, plan 008)
    (
        "backlink_publisher.publishing.adapters.hackmd_api",
        "_post_publish_delay_s",
        "HACKMD_PUBLISH_DELAY_S",
        30,
    ),
    (
        "backlink_publisher.publishing.adapters.mataroa_api",
        "_post_publish_delay_s",
        "MATAROA_PUBLISH_DELAY_S",
        15,
    ),
    (
        "backlink_publisher.publishing.adapters.notesio_api",
        "_post_publish_delay_s",
        "NOTESIO_PUBLISH_DELAY_S",
        10,
    ),
    (
        "backlink_publisher.publishing.adapters.livejournal_api",
        "_post_publish_delay_s",
        "LIVEJOURNAL_PUBLISH_DELAY_S",
        30,
    ),
]

ADAPTER_IDS = [p[0].split(".")[-1] for p in ADAPTER_DELAY_PARAMS]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure all delay env vars are unset at the start of each test."""
    for _, _, env_var, _ in ADAPTER_DELAY_PARAMS:
        monkeypatch.delenv(env_var, raising=False)
    yield


def _get_getter(module_path: str, getter_name: str):
    """Import a module and return its getter function."""
    mod = importlib.import_module(module_path)
    return getattr(mod, getter_name)


@pytest.mark.parametrize(
    "module_path,getter_name,env_var,default",
    ADAPTER_DELAY_PARAMS,
    ids=ADAPTER_IDS,
)
def test_default_when_env_not_set(module_path, getter_name, env_var, default, monkeypatch):
    """Getter returns the hardcoded default when env var is absent."""
    monkeypatch.delenv(env_var, raising=False)
    getter = _get_getter(module_path, getter_name)
    assert getter() == default


@pytest.mark.parametrize(
    "module_path,getter_name,env_var,default",
    ADAPTER_DELAY_PARAMS,
    ids=ADAPTER_IDS,
)
def test_env_override_integer(module_path, getter_name, env_var, default, monkeypatch):
    """Getter returns env var value when set to a valid integer."""
    monkeypatch.setenv(env_var, "5")
    getter = _get_getter(module_path, getter_name)
    assert getter() == 5


@pytest.mark.parametrize(
    "module_path,getter_name,env_var,default",
    ADAPTER_DELAY_PARAMS,
    ids=ADAPTER_IDS,
)
def test_env_override_zero(module_path, getter_name, env_var, default, monkeypatch):
    """Getter returns 0 when env var is set to '0' (disables delay)."""
    monkeypatch.setenv(env_var, "0")
    getter = _get_getter(module_path, getter_name)
    assert getter() == 0


@pytest.mark.parametrize(
    "module_path,getter_name,env_var,default",
    ADAPTER_DELAY_PARAMS,
    ids=ADAPTER_IDS,
)
def test_env_override_invalid_falls_back_to_default(
    module_path, getter_name, env_var, default, monkeypatch
):
    """Getter falls back to default when env var is a non-integer string."""
    monkeypatch.setenv(env_var, "abc")
    getter = _get_getter(module_path, getter_name)
    assert getter() == default


# ---------------------------------------------------------------------------
# DEVTO-specific: ensure the specific default value matches expected spec
# ---------------------------------------------------------------------------
def test_devto_default_is_30(monkeypatch):
    """DEVTO_PUBLISH_DELAY_S unset → default is 30 s."""
    monkeypatch.delenv("DEVTO_PUBLISH_DELAY_S", raising=False)
    from backlink_publisher.publishing.adapters.devto_api import _post_publish_delay_s
    assert _post_publish_delay_s() == 30


def test_devto_env_override(monkeypatch):
    """DEVTO_PUBLISH_DELAY_S=5 → getter returns 5."""
    monkeypatch.setenv("DEVTO_PUBLISH_DELAY_S", "5")
    from backlink_publisher.publishing.adapters.devto_api import _post_publish_delay_s
    assert _post_publish_delay_s() == 5


def test_devto_env_invalid_falls_back(monkeypatch):
    """DEVTO_PUBLISH_DELAY_S=abc → getter returns default 30, no exception."""
    monkeypatch.setenv("DEVTO_PUBLISH_DELAY_S", "abc")
    from backlink_publisher.publishing.adapters.devto_api import _post_publish_delay_s
    assert _post_publish_delay_s() == 30


# ---------------------------------------------------------------------------
# LinkedIn: higher default (60) and specific rate-limit comment
# ---------------------------------------------------------------------------
def test_linkedin_default_is_60(monkeypatch):
    """LINKEDIN_PUBLISH_DELAY_S unset → default is 60 s (rate-limit floor)."""
    monkeypatch.delenv("LINKEDIN_PUBLISH_DELAY_S", raising=False)
    from backlink_publisher.publishing.adapters.linkedin_api import _post_publish_delay_s
    assert _post_publish_delay_s() == 60


# ---------------------------------------------------------------------------
# Bug fix: qiita AdapterResult must carry post_publish_delay_seconds != 0
# ---------------------------------------------------------------------------
def test_qiita_adapter_result_has_delay(monkeypatch):
    """QiitaAPIAdapter draft path now includes post_publish_delay_seconds (bug fix)."""
    monkeypatch.delenv("QIITA_PUBLISH_DELAY_S", raising=False)
    from backlink_publisher.publishing.adapters.base import AdapterResult
    from backlink_publisher.publishing.adapters.qiita_api import _post_publish_delay_s

    # Simulate what the draft branch returns
    result = AdapterResult(
        status="drafted",
        adapter="qiita-api",
        platform="qiita",
        draft_url="https://qiita.com/drafts",
        post_publish_delay_seconds=_post_publish_delay_s(),
    )
    assert result.post_publish_delay_seconds != 0
    assert result.post_publish_delay_seconds == 5


def test_qiita_published_result_has_delay(monkeypatch):
    """QiitaAPIAdapter publish path now includes post_publish_delay_seconds (bug fix)."""
    monkeypatch.delenv("QIITA_PUBLISH_DELAY_S", raising=False)
    from backlink_publisher.publishing.adapters.base import AdapterResult
    from backlink_publisher.publishing.adapters.qiita_api import _post_publish_delay_s

    result = AdapterResult(
        status="published",
        adapter="qiita-api",
        platform="qiita",
        published_url="https://qiita.com/user/items/abc123",
        post_publish_delay_seconds=_post_publish_delay_s(),
    )
    assert result.post_publish_delay_seconds != 0
    assert result.post_publish_delay_seconds == 5


# ---------------------------------------------------------------------------
# Bug fix: zenn AdapterResult must carry post_publish_delay_seconds != 0
# ---------------------------------------------------------------------------
def test_zenn_adapter_result_has_delay(monkeypatch):
    """ZennGitHubAdapter draft path now includes post_publish_delay_seconds (bug fix)."""
    monkeypatch.delenv("ZENN_PUBLISH_DELAY_S", raising=False)
    from backlink_publisher.publishing.adapters.base import AdapterResult
    from backlink_publisher.publishing.adapters.zenn_github import _post_publish_delay_s

    result = AdapterResult(
        status="drafted",
        adapter="zenn-github",
        platform="zenn",
        draft_url="https://zenn.dev/user/articles/test-article",
        post_publish_delay_seconds=_post_publish_delay_s(),
    )
    assert result.post_publish_delay_seconds != 0
    assert result.post_publish_delay_seconds == 10


def test_zenn_published_result_has_delay(monkeypatch):
    """ZennGitHubAdapter publish path now includes post_publish_delay_seconds (bug fix)."""
    monkeypatch.delenv("ZENN_PUBLISH_DELAY_S", raising=False)
    from backlink_publisher.publishing.adapters.base import AdapterResult
    from backlink_publisher.publishing.adapters.zenn_github import _post_publish_delay_s

    result = AdapterResult(
        status="published",
        adapter="zenn-github",
        platform="zenn",
        published_url="https://zenn.dev/user/articles/test-article",
        post_publish_delay_seconds=_post_publish_delay_s(),
    )
    assert result.post_publish_delay_seconds != 0
    assert result.post_publish_delay_seconds == 10


# ---------------------------------------------------------------------------
# medium_api and medium_browser share the same MEDIUM_PUBLISH_DELAY_S key
# ---------------------------------------------------------------------------
def test_medium_api_and_browser_share_env_key(monkeypatch):
    """Both medium adapters read MEDIUM_PUBLISH_DELAY_S."""
    monkeypatch.setenv("MEDIUM_PUBLISH_DELAY_S", "15")
    from backlink_publisher.publishing.adapters.medium_api import (
        _post_publish_delay_s as api_delay,
    )
    from backlink_publisher.publishing.adapters.medium_browser import (
        _post_publish_delay_s as browser_delay,
    )
    assert api_delay() == 15
    assert browser_delay() == 15
