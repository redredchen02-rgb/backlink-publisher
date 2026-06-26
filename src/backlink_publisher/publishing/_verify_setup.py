"""Offline setup checks and the public ``verify_adapter_setup`` entry point.

Extracted from ``_verify_adapters.py`` (Wave 3 Unit 3).  Contains the
per-platform credential/config readiness checks (``_check_*_setup``), the
``_SETUP_CHECKS`` dispatch table, and the three-tier ``verify_adapter_setup``
function.

``_verify_live`` lives in ``_verify_live_probes`` and is imported lazily
inside ``verify_adapter_setup`` to avoid a circular module-level import
(``_verify_live_probes`` imports ``verify_adapter_setup`` at module level).

``_verify_adapters.py`` re-exports all public names for backward compatibility.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from backlink_publisher._util.errors import DependencyError
from backlink_publisher.config import Config

from ._verify import (
    dry_run_intercept,
    DryRunInterceptError,
    VerifyResult,
)
from .registry import _REGISTRY, registered_platforms

# ── Offline setup checks ─────────────────────────────────────────────


def _check_medium_setup(config: Config) -> str | None:
    from backlink_publisher.config import load_medium_token
    from backlink_publisher.config.tokens import load_medium_integration_token

    has_oauth = bool(load_medium_token())
    it_data = load_medium_integration_token()
    has_it = bool(it_data and it_data.get("integration_token", "").strip())
    has_toml_it = bool(config.medium_integration_token)
    from .adapters.medium_browser import sync_playwright as _spw

    has_playwright = _spw is not None
    if not (has_it or has_toml_it or has_oauth or has_playwright):
        return (
            "Medium adapter not ready: no integration_token, no OAuth token file, "
            "and Playwright is not installed. "
            "Run 'playwright install chromium' or configure a token in /settings."
        )
    return None


def _check_ghpages_setup(config: Config) -> str | None:
    if config.ghpages is None or not config.ghpages.repo:
        return (
            "GitHub Pages config missing. Add [ghpages] repo=\"owner/name\" "
            "to ~/.config/backlink-publisher/config.toml"
        )
    if not config.ghpages_token_path.exists():
        return (
            "GitHub Pages PAT not stored. Write "
            f"{{\"token\": \"<pat>\"}} to {config.ghpages_token_path} "
            "(chmod 600). PAT needs Contents:Read+Write on the target repo."
        )
    return None


def _check_velog_setup(config: Config) -> str | None:
    velog_cfg = config.velog
    cookies_path = (
        velog_cfg.cookies_path
        if velog_cfg
        else config.config_dir / "velog-cookies.json"
    )
    if not cookies_path.exists():
        return (
            f"velog cookies not found: {cookies_path}\n"
            "Run: velog-login"
        )
    return None


def _check_telegraph_setup(config: Config) -> str | None:
    from .adapters.telegraph_api import verify_telegraph_setup

    try:
        verify_telegraph_setup(config)
        return None
    except DependencyError as e:
        return str(e)


# Lazy adapter imports inside lambdas avoid circular deps at import time.
from .adapters.devto_api import DevtoAPIAdapter
from .adapters.gitlabpages import GitLabPagesAPIAdapter
from .adapters.hackmd_api import HackmdAPIAdapter
from .adapters.hatena_atompub import HatenaAtomPubAdapter
from .adapters.mataroa_api import MataroaAPIAdapter
from .adapters.notion_api import NotionAPIAdapter

_SETUP_CHECKS: dict[str, Callable[[Config], str | None]] = {
    "blogger": lambda c: (
        None
        if c.blogger_oauth
        else "Blogger OAuth not configured. "
        "Add [blogger.oauth] to ~/.config/backlink-publisher/config.toml"
    ),
    "medium": _check_medium_setup,
    "telegraph": _check_telegraph_setup,
    "velog": _check_velog_setup,
    "ghpages": _check_ghpages_setup,
    "notion": lambda c: (
        None
        if NotionAPIAdapter.available(c)
        else (
            "Notion integration token or database_id not configured. "
            f"Write {{\"integration_token\": \"secret_...\", \"database_id\": \"...\"}} "
            f"to {c.notion_token_path} (chmod 600). "
            "Create an Integration at https://www.notion.so/my-integrations."
        )
    ),
    "devto": lambda c: (
        None
        if DevtoAPIAdapter.available(c)
        else (
            "Dev.to API key not configured. "
            f"Write {{\"api_key\": \"<key>\"}} to {c.devto_token_path} "
            "(chmod 600). Generate at https://dev.to/settings/extensions."
        )
    ),
    "hackmd": lambda c: (
        None
        if HackmdAPIAdapter.available(c)
        else (
            "HackMD API token not configured. "
            f"Write {{\"token\": \"<token>\"}} to {c.hackmd_token_path} "
            "(chmod 600). Generate at HackMD → Settings → API → Create token."
        )
    ),
    "mataroa": lambda c: (
        None
        if MataroaAPIAdapter.available(c)
        else (
            "Mataroa API token not configured. "
            f"Write {{\"token\": \"<token>\"}} to {c.mataroa_token_path} "
            "(chmod 600). Enable at mataroa.blog → account settings → API."
        )
    ),
    "gitlabpages": lambda c: (
        None
        if GitLabPagesAPIAdapter.available(c)
        else (
            "GitLab Pages not configured. Add [gitlabpages] project=\"namespace/name\" "
            f"to config.toml and write {{\"token\": \"<pat>\"}} to {c.gitlabpages_token_path} "
            "(chmod 600, `api` scope). PRECONDITION: the target project must already "
            "have a `pages` CI job emitting public/ — committing a file does not "
            "publish without it."
        )
    ),
    "hatena": lambda c: (
        None
        if HatenaAtomPubAdapter.available(c)
        else (
            "Hatena credentials not configured. Write "
            "{\"hatena_id\": \"...\", \"blog_id\": \"...\", \"api_key\": \"...\"} to "
            f"{c.config_dir / 'hatena-credentials.json'} (chmod 600). "
            "API key: Hatena Blog → Settings → Advanced → AtomPub."
        )
    ),
}


# ── Public entry point ──────────────────────────────────────────────


def verify_adapter_setup(
    platform: str,
    config: Config,
    *,
    mode: Literal["offline", "live", "dry-run"] = "offline",
    payload: dict[str, Any] | None = None,
) -> VerifyResult | None:
    """Three-tier adapter setup verification.

    ``mode='offline'`` (default): raise ``DependencyError`` on failure,
    return ``None`` on success (pre-Unit-2 contract).

    ``mode='live'``: hit the platform's real API and return a ``VerifyResult``.
    Never raises for auth/config failures — returns structured result instead.

    ``mode='dry-run'``: build payload via adapter under HTTP intercept and
    return a ``VerifyResult`` with ``last_verify_result='unverifiable_live'``
    until per-adapter dry-run is wired (Unit 6 deliverable).
    """
    if mode == "live":
        from ._verify_live_probes import _verify_live
        return _verify_live(platform, config)
    if mode == "dry-run":
        return _verify_dry_run(platform, config, payload or {})

    # mode == "offline" — dispatch table first, then registry-driven fallback
    check = _SETUP_CHECKS.get(platform)
    if check is not None:
        error = check(config)
        if error:
            raise DependencyError(error)
        return None

    # ── Plan 2026-05-26-002 Unit 1: registry-driven fallback ──────────────
    if platform not in registered_platforms():
        raise DependencyError(f"No adapter configured for platform: {platform}")

    if platform == "livejournal":
        cred = config.config_dir / "livejournal-credentials.json"
        if cred.exists():
            return None
        raise DependencyError(
            "LiveJournal not bound: no stored credentials. Save "
            f'{{"username": "...", "hpassword": "..."}} to {cred} '
            "(use a throwaway account — the secret is password-equivalent)."
        )

    if platform == "mastodon":
        profile = config.config_dir / "real-chrome-profile" / "mastodon"
        if profile.exists() and any(profile.iterdir()):
            return None
        raise DependencyError(
            f"Mastodon not bound: no Chrome login profile at {profile}. "
            "Bind via browser login (set [mastodon] instance_url first)."
        )

    _entry = _REGISTRY.get(platform)
    chain = _entry.publishers if _entry else []
    for entry in chain:
        publisher_cls = entry if isinstance(entry, type) else type(entry)
        if publisher_cls.available(config):
            return None
    raise DependencyError(f"{platform} not bound: credentials not configured.")


# ── Dry-run verify ──────────────────────────────────────────────────


def _verify_dry_run(
    platform: str, config: Config, payload: dict[str, Any]
) -> VerifyResult:
    """Dry-run mode: build payload via adapter.publish() under intercept."""
    if platform not in registered_platforms():
        return VerifyResult(
            ok=False,
            last_verify_result="never",
            blockers=[f"no adapter configured for platform: {platform}"],
        )

    try:
        with dry_run_intercept():
            pass
    except DryRunInterceptError as e:
        return VerifyResult(
            ok=False,
            last_verify_result="payload_invalid",
            blockers=[f"dry-run intercept fired: {e}"],
        )

    return VerifyResult(
        ok=True,
        last_verify_result="unverifiable_live",
        blockers=["per-adapter dry-run not yet implemented (Unit 6 deliverable)"],
    )
