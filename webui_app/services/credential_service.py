"""Credential-persistence service — Plan 2026-06-01-001 U3b.

Flask-free: no request/session access.  Routes extract form data, apply
security gates (SSRF, blob schema), then delegate writes here.

Maps exported at module level so test_credential_save_dispatch_drift.py can
guard them without importing from routes (see plan section R8/R9).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from backlink_publisher.config import Config
from backlink_publisher.config.tokens import (
    save_devto_token,
    save_ghpages_token,
    save_gitlabpages_token,
    save_hackmd_token,
    save_hatena_token,
    save_mataroa_token,
    save_qiita_token,
    save_tumblr_token,
    save_wordpresscom_token,
    save_zenn_token,
)
from backlink_publisher._util.io import atomic_write_json

_log = logging.getLogger(__name__)


class ChannelNotConfigured(Exception):
    """Raised when no dispatch entry exists for the requested channel."""


class CorruptCredentialFile(Exception):
    """Raised when an existing credential file cannot be parsed (not valid JSON).

    Callers should surface this to the operator with the file path so they can
    inspect and delete the file rather than silently overwriting it.
    """


# ── Dispatch maps (single source of truth) ───────────────────────────────────

# TOKEN — single secret field.  auth_type="token" channels.
# (channel) → (save_fn, basename, token_field_key)
_TOKEN_DISPATCH: dict[str, tuple] = {
    "devto":   (save_devto_token,   "devto-token.json",   "api_key"),
    "hackmd":  (save_hackmd_token,  "hackmd-token.json",  "token"),
    "mataroa": (save_mataroa_token, "mataroa-token.json", "token"),
    "qiita":   (save_qiita_token,   "qiita-token.json",   "token"),
}

# TOKEN+FIELDS — secret + extra config fields; field-merge semantics.
# auth_type="token_fields" channels.
# (channel) → (save_fn, basename, [field_names])
# ghpages uses a single "token" field but is registered as token_fields.
_TOKEN_FIELDS_DISPATCH: dict[str, tuple] = {
    "tumblr":       (save_tumblr_token,       "tumblr-credentials.json",
                     ["consumer_key", "consumer_secret", "oauth_token",
                      "oauth_token_secret", "blog_identifier"]),
    "wordpresscom": (save_wordpresscom_token, "wordpresscom-token.json",
                     ["token", "site"]),
    "ghpages":      (save_ghpages_token,      "ghpages-token.json",
                     ["token"]),
    "gitlabpages":  (save_gitlabpages_token,  "gitlabpages-token.json",
                     ["token"]),
    "hatena":       (save_hatena_token,       "hatena-credentials.json",
                     ["hatena_id", "blog_id", "api_key"]),
    "zenn":         (save_zenn_token,         "zenn-token.json",
                     ["token", "github_repo", "username"]),
}

# PASTE-BLOB — pasted {"cookies":[...]} JSON; domain advisory check.
# (channel) → (basename, expected_domain_suffix)
_PASTE_BLOB_CHANNELS: dict[str, tuple[str, str]] = {
    "substack": ("substack-credentials.json", "substack.com"),
}
_PASTE_BLOB_MAX_BYTES = 100_000

# USERPASS — credential-path basenames.  Must NOT be interpolated from channel.
_USERPASS_CRED_BASENAMES: dict[str, str] = {
    "livejournal": "livejournal-credentials.json",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def token_field_names(channel: str) -> list[str] | None:
    """Return form-field names for a token_fields channel, or None if unknown."""
    entry = _TOKEN_FIELDS_DISPATCH.get(channel)
    return list(entry[2]) if entry else None


def paste_blob_expected_domain(channel: str) -> str | None:
    """Return the advisory domain suffix for a paste-blob channel, or None."""
    entry = _PASTE_BLOB_CHANNELS.get(channel)
    return entry[1] if entry else None


# ── Save functions ────────────────────────────────────────────────────────────

def save_token(channel: str, config: Config, token: str) -> Path:
    """Write a single-token credential for *channel*."""
    entry = _TOKEN_DISPATCH.get(channel)
    if entry is None:
        raise ChannelNotConfigured(channel)
    save_fn, basename, field_key = entry
    config.config_dir.mkdir(parents=True, exist_ok=True)
    save_fn({field_key: token})
    return config.config_dir / basename


def save_token_fields(channel: str, config: Config, new_fields: dict) -> Path:
    """Merge-write token+fields credential for *channel*.

    Unsubmitted fields in the existing file are preserved (field-merge, not
    full replace).  Corrupt existing files are treated as empty — BF2 makes
    this fail-loud after U3b lands.
    """
    entry = _TOKEN_FIELDS_DISPATCH.get(channel)
    if entry is None:
        raise ChannelNotConfigured(channel)
    save_fn, basename, _field_names = entry
    token_path = config.config_dir / basename
    existing: dict = {}
    if token_path.exists():
        try:
            existing = json.loads(token_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CorruptCredentialFile(
                f"{token_path} 无法解析为 JSON — 请删除该文件后重试 ({exc})"
            ) from exc
        except OSError as exc:
            raise CorruptCredentialFile(
                f"{token_path} 读取失败 ({exc})"
            ) from exc
    merged = {**existing, **new_fields}
    config.config_dir.mkdir(parents=True, exist_ok=True)
    save_fn(merged)
    return token_path


def save_paste_blob(channel: str, config: Config, blob: dict) -> Path:
    """Write a paste-blob (cookie JSON) credential for *channel*."""
    entry = _PASTE_BLOB_CHANNELS.get(channel)
    if entry is None:
        raise ChannelNotConfigured(channel)
    basename, _domain = entry
    cred_path = config.config_dir / basename
    cred_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(cred_path, blob, mode=0o600)
    return cred_path


def save_userpass(channel: str, config: Config, username: str, password: str) -> Path:
    """Write userpass credentials via the registry credential_saver for *channel*."""
    from backlink_publisher.publishing.registry import credential_saver as _registry_saver  # lazy
    saver = _registry_saver(channel)
    if saver is None:
        raise ChannelNotConfigured(channel)
    return saver(channel, config, {"username": username, "password": password}, "replace")


# ── Clear ─────────────────────────────────────────────────────────────────────

def clear_credential(channel: str, auth_type: str, config: Config) -> bool:
    """Unlink the credential file for *channel*.

    Returns True if a file was removed, False if it did not exist.
    Raises ChannelNotConfigured if no path is known for the channel+auth_type.
    Raises OSError if the unlink fails.
    """
    path = _credential_path(channel, auth_type, config)
    if path is None:
        raise ChannelNotConfigured(channel)
    if path.exists():
        path.unlink()
        return True
    return False


def _credential_path(channel: str, auth_type: str, config: Config) -> Path | None:
    """Resolve the credential file path for a channel — basenames from static maps only."""
    if auth_type == "token":
        entry = _TOKEN_DISPATCH.get(channel)
        return config.config_dir / entry[1] if entry else None
    if auth_type == "token_fields":
        entry = _TOKEN_FIELDS_DISPATCH.get(channel)
        return config.config_dir / entry[1] if entry else None
    if auth_type == "paste_blob":
        entry = _PASTE_BLOB_CHANNELS.get(channel)
        return config.config_dir / entry[0] if entry else None
    if auth_type == "userpass":
        basename = _USERPASS_CRED_BASENAMES.get(channel)
        return config.config_dir / basename if basename else None
    return None
