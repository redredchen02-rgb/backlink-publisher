"""Adapter dispatcher — table-driven registry (Plan Unit 7).

Replaced the if/elif chain in the previous ``publish()`` with a
single ``dispatch()`` call into ``publishing.registry``. The Medium
fallback chain (MediumAPI → MediumBrave on macOS → MediumBrowser
on Playwright) is now expressed as registration order, and the
macOS gate lives on ``MediumBraveAdapter.available()``.

Behaviour preserved verbatim:

  - Blogger: ``BloggerAPIAdapter`` only.
  - Medium:
      1. ``MediumAPIAdapter`` (Integration Token; deprecated by Medium 2023)
      2. ``MediumBraveAdapter`` (AppleScript + Brave; macOS only;
         ``available()`` short-circuits elsewhere)
      3. ``MediumBrowserAdapter`` (Playwright headed Chrome — terminal)
  - ``DependencyError`` from one adapter → try the next.
  - ``ExternalServiceError`` (401 / 429 / network) → propagate, no fall.
  - ``dry_run=True`` → sentinel ``AdapterResult`` without publishing.
  - Unknown platform → ``ExternalServiceError("unsupported platform: …")``.
"""

from __future__ import annotations

__all__ = [
    "AdapterResult",
    "Any",
    "BLOGGER_MANIFEST",
    "BloggerAPIAdapter",
    "BrowserPublishDispatcher",
    "DEVTO_MANIFEST",
    "DevtoAPIAdapter",
    "GHPAGES_MANIFEST",
    "GITLABPAGES_MANIFEST",
    "GitHubPagesAPIAdapter",
    "GitLabPagesAPIAdapter",
    "HACKMD_MANIFEST",
    "HASHNODE_MANIFEST",
    "HATENA_MANIFEST",
    "HackmdAPIAdapter",
    "HashnodeGraphQLAdapter",
    "HatenaAtomPubAdapter",
    "LINKEDIN_MANIFEST",
    "LIVEJOURNAL_MANIFEST",
    "LinkedInAPIAdapter",
    "Literal",
    "LivejournalAPIAdapter",
    "MASTODON_MANIFEST",
    "MATAROA_MANIFEST",
    "MEDIUM_MANIFEST",
    "MataroaAPIAdapter",
    "MediumAPIAdapter",
    "MediumBraveAdapter",
    "MediumBrowserAdapter",
    "NOTESIO_MANIFEST",
    "NOTION_MANIFEST",
    "NotesioFormPostAdapter",
    "NotionAPIAdapter",
    "Optional",
    "QIITA_MANIFEST",
    "QiitaAPIAdapter",
    "RENTRY_MANIFEST",
    "RentryAPIAdapter",
    "SUBSTACK_MANIFEST",
    "SubstackAPIAdapter",
    "TELEGRAPH_MANIFEST",
    "TUMBLR_MANIFEST",
    "TXTFYI_MANIFEST",
    "TYPE_CHECKING",
    "TelegraphAPIAdapter",
    "TelegraphCdpAdapter",
    "TumblrAPIAdapter",
    "TxtfyiFormPostAdapter",
    "VELOG_MANIFEST",
    "VelogGraphQLAdapter",
    "VerifyResult",
    "WORDPRESSCOM_MANIFEST",
    "WRITEAS_MANIFEST",
    "WordpresscomAPIAdapter",
    "WriteasAPIAdapter",
    "ZENN_MANIFEST",
    "ZennGitHubAdapter",
    "dispatch",
    "publish",
    "register",
    "register_all_adapters",
    "register_catalog_entries",
    "registered_platforms",
    "verify_adapter_setup",
]
from typing import Any, Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backlink_publisher.config import Config

from .._manifests import (
    BLOGGER_MANIFEST,
    DEVTO_MANIFEST,
    GHPAGES_MANIFEST,
    GITLABPAGES_MANIFEST,
    HACKMD_MANIFEST,
    HASHNODE_MANIFEST,
    HATENA_MANIFEST,
    LINKEDIN_MANIFEST,
    LIVEJOURNAL_MANIFEST,
    MASTODON_MANIFEST,
    MATAROA_MANIFEST,
    MEDIUM_MANIFEST,
    NOTESIO_MANIFEST,
    NOTION_MANIFEST,
    QIITA_MANIFEST,
    RENTRY_MANIFEST,
    SUBSTACK_MANIFEST,
    TELEGRAPH_MANIFEST,
    TUMBLR_MANIFEST,
    TXTFYI_MANIFEST,
    VELOG_MANIFEST,
    WORDPRESSCOM_MANIFEST,
    WRITEAS_MANIFEST,
    ZENN_MANIFEST,
)
from .._verify import VerifyResult
from ..registry import dispatch, register, registered_platforms
from ._nofollow_rationales import NOFOLLOW_RATIONALES as _R
from ._setup_checks import _verify_offline_setup
from ._verify_live import _verify_dry_run, _verify_live
from .base import AdapterResult


# Register the fallback chain per platform. Adding a new platform = one
# more ``register(...)`` call — no dispatcher changes. Each registration
# declares ``dofollow=True|False|"uncertain"`` (R1 / Plan 2026-05-20-009);
# ``False`` and ``"uncertain"`` additionally require ``rationale=`` of
# ≥80 stripped chars (R3, mirrors ``monolith_budget.toml`` discipline).
#
# ``TelegraphCdpAdapter`` (imported from ``instant_web.py``) is the
# Chrome/CDP fallback for the "telegraph" channel. It is registered
# after ``TelegraphAPIAdapter`` in the channel chain below (2026-06-03).
# Manifest declarations for migrated channels live in
# ``publishing/_manifests.py`` (Plan 2026-05-25-002 Phase 2). Adding a
# channel = new ``<SLUG>_MANIFEST`` dict in that file + new
# ``**<SLUG>_MANIFEST`` splat here. The dispatcher module stays focused
# on register() wiring and adapter imports.
def register_all_adapters() -> None:
    """Idempotent, explicit adapter-registry bootstrap.

    Imports are deferred inside this function so importing this module does NOT
    eagerly load any adapter module (requests, bs4, google-api-python-client, etc.)
    — only calling this function (or accessing any public name via __getattr__)
    triggers the full import chain.
    """
    if "blogger" in registered_platforms():
        return
    # Deferred imports: avoid loading heavy adapter modules at import time.
    from ..browser_publish import BrowserPublishDispatcher
    from ..browser_publish.recipes import devto as _devto_recipe
    from ..browser_publish.recipes import mastodon as _mastodon_recipe
    from ..browser_publish.recipes import velog as _velog_recipe
    from .blogger_api import BloggerAPIAdapter
    from .devto_api import DevtoAPIAdapter
    from .ghpages import GitHubPagesAPIAdapter
    from .gitlabpages import GitLabPagesAPIAdapter
    from .hackmd_api import HackmdAPIAdapter
    from .hashnode_graphql import HashnodeGraphQLAdapter
    from .hatena_atompub import HatenaAtomPubAdapter
    from .instant_web import TelegraphCdpAdapter
    from .linkedin_api import LinkedInAPIAdapter
    from .livejournal_api import _livejournal_credential_saver, LivejournalAPIAdapter
    from .mataroa_api import MataroaAPIAdapter
    from .medium_api import MediumAPIAdapter
    from .medium_brave import MediumBraveAdapter
    from .medium_browser import MediumBrowserAdapter
    from .notesio_api import NotesioFormPostAdapter
    from .notion_api import NotionAPIAdapter
    from .qiita_api import QiitaAPIAdapter
    from .rentry_api import RentryAPIAdapter
    from .substack_api import SubstackAPIAdapter
    from .telegraph_api import TelegraphAPIAdapter
    from .tumblr_api import TumblrAPIAdapter
    from .txtfyi_api import TxtfyiFormPostAdapter
    from .velog_graphql import VelogGraphQLAdapter
    from .wordpresscom_api import WordpresscomAPIAdapter
    from .writeas_api import WriteasAPIAdapter
    from .zenn_github import ZennGitHubAdapter

    register("blogger", BloggerAPIAdapter, dofollow=True, **BLOGGER_MANIFEST)
    # Phase 1 dofollow truth audit (2026-05-26): every adapter below shipped
    # with bare ``dofollow=True`` and no evidence. Hard server-side
    # nofollow/redirect-interstitial evidence => dofollow=False; no
    # OUR-pipeline canary => dofollow="uncertain". Rationales live in
    # ``_nofollow_rationales`` (_R). Operator flips "uncertain" -> True by
    # running a fresh canary and reading verify_link_attributes (the
    # livejournal/txtfyi workflow).
    register(
        "wordpresscom",
        WordpresscomAPIAdapter,
        dofollow="uncertain",  # evidence conflict (#108->#109 vs 2026-05 recheck); canary pending
        rationale=_R["wordpresscom"],
        referral_value="high",
        **WORDPRESSCOM_MANIFEST,
    )
    register(
        "hashnode",
        HashnodeGraphQLAdapter,
        dofollow="uncertain",
        rationale=_R["hashnode"],
        referral_value="high",
        visibility="retired",
        **HASHNODE_MANIFEST,
    )
    register(
        "writeas",
        WriteasAPIAdapter,
        dofollow="uncertain",
        rationale=_R["writeas"],
        referral_value="low",
        visibility="retired",
        **WRITEAS_MANIFEST,
    )
    register(
        "substack",
        SubstackAPIAdapter,
        dofollow="uncertain",  # 3rd-party live check = dofollow; OUR canary pending
        rationale=_R["substack"],
        referral_value="high",
        **SUBSTACK_MANIFEST,
    )
    register(
        "rentry",
        RentryAPIAdapter,
        dofollow=True,  # OUR canary 2026-06-05: dofollow confirmed (2x, rel empty)
        **RENTRY_MANIFEST,
    )
    register(
        "linkedin",
        LinkedInAPIAdapter,
        dofollow=False,
        rationale=_R["linkedin"],
        referral_value="high",
        **LINKEDIN_MANIFEST,
        visibility="experimental",
    )
    register(
        "tumblr",
        TumblrAPIAdapter,
        dofollow=False,
        rationale=_R["tumblr"],
        referral_value="high",
        **TUMBLR_MANIFEST,
    )
    register(
        "medium",
        MediumAPIAdapter,
        MediumBraveAdapter,
        MediumBrowserAdapter,
        dofollow=True,
        **MEDIUM_MANIFEST,
    )
    register(
        "telegraph", TelegraphAPIAdapter, TelegraphCdpAdapter, dofollow=True, **TELEGRAPH_MANIFEST
    )
    register(
        "velog",
        VelogGraphQLAdapter,
        BrowserPublishDispatcher.for_channel("velog"),
        dofollow=True,
        **VELOG_MANIFEST,
    )
    register("ghpages", GitHubPagesAPIAdapter, dofollow=True, **GHPAGES_MANIFEST)
    register(
        "livejournal",
        LivejournalAPIAdapter,
        dofollow=False,
        rationale=_R["livejournal"],
        referral_value="high",
        credential_saver=_livejournal_credential_saver,
        **LIVEJOURNAL_MANIFEST,
    )
    register(
        "txtfyi",
        TxtfyiFormPostAdapter,
        dofollow="uncertain",  # R4 canary pending; Phase 0 preliminary = dofollow
        rationale=_R["txtfyi"],
        referral_value="low",  # anonymous pastebin; modest DA + R4 pending
        **TXTFYI_MANIFEST,
    )
    register(
        "notesio",
        NotesioFormPostAdapter,
        dofollow="uncertain",  # R4 canary pending; 3rd-party probe 12/0 dofollow
        rationale=_R["notesio"],
        referral_value="low",  # anonymous pastebin; modest DA + R4 pending
        **NOTESIO_MANIFEST,
    )
    register(
        "devto",
        DevtoAPIAdapter,
        BrowserPublishDispatcher.for_channel("devto"),
        dofollow=False,
        rationale=_R["devto"],
        referral_value="high",  # high DA + referral traffic + topical signal
        **DEVTO_MANIFEST,
    )
    register(
        "notion",
        NotionAPIAdapter,
        dofollow=False,
        rationale=_R["notion"],
        referral_value="high",  # DA ~75+, entity signal, indexation speed
        **NOTION_MANIFEST,
    )
    register(
        "hatena",
        HatenaAtomPubAdapter,
        dofollow="uncertain",  # 3rd-party probe = dofollow (11/12); OUR canary pending
        rationale=_R["hatena"],
        referral_value="high",  # JP high-DA + referral + indexation; AtomPub publish API
        **HATENA_MANIFEST,
    )
    register(
        "mastodon",
        BrowserPublishDispatcher.for_channel("mastodon"),
        dofollow=False,
        rationale=_R["mastodon"],
        **MASTODON_MANIFEST,
        referral_value="high",  # Fediverse referral traffic + topical signal
    )
    # Plan 2026-06-01-007 Wave 1 — three new channels, all dofollow="uncertain"
    # pending an OUR-pipeline canary (the hashnode/substack/hatena discipline; the
    # canary-pending tracking artifact + deadline gate live in docs/discovery/).
    register(
        "hackmd",
        HackmdAPIAdapter,
        dofollow=False,  # OUR canary 2026-06-05: nofollow confirmed (rel="noopener ugc nofollow")
        rationale=_R["hackmd"],
        referral_value="high",
        **HACKMD_MANIFEST,
    )
    register(
        "mataroa",
        MataroaAPIAdapter,
        dofollow=True,  # OUR canary 2026-06-05: dofollow confirmed (2x, rel empty)
        **MATAROA_MANIFEST,
    )
    register(
        "gitlabpages",
        GitLabPagesAPIAdapter,
        dofollow="uncertain",  # rel operator-controlled, but *.gitlab.io index partial + async; OUR canary pending
        rationale=_R["gitlabpages"],
        referral_value="high",
        **GITLABPAGES_MANIFEST,
    )
    # Wave-2 discovery (2026-06-01) — confirmed nofollow, high JP referral value.
    register(
        "qiita",
        QiitaAPIAdapter,
        dofollow=False,  # confirmed rel=nofollow noopener on all outbound links
        rationale=_R["qiita"],
        referral_value="high",  # top JP dev platform, DA ~90+, high referral traffic
        **QIITA_MANIFEST,
    )
    register(
        "zenn",
        ZennGitHubAdapter,
        dofollow=False,  # confirmed rel=nofollow noopener noreferrer (36/137)
        rationale=_R["zenn"],
        referral_value="high",  # top JP dev platform, DA ~90+, high referral traffic
        **ZENN_MANIFEST,
    )


_INITIALIZED: bool = False


def _lazy_init() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True
    register_all_adapters()
    register_catalog_entries(built_in_dir=_builtin_catalog)


def __getattr__(name: str) -> Any:
    if not name.startswith("_"):
        _lazy_init()
        if name in globals():
            return globals()[name]
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return sorted(__all__)


def publish(
    payload: dict[str, Any],
    mode: str,
    config: Config,
    dry_run: bool = False,
    *,
    banner_emit: Any = None,
) -> AdapterResult:
    """Public dispatch entry point — preserved as a function for backward
    compatibility (CLI / tests / WebUI all call ``publish(...)``).

    ``banner_emit`` (Plan 2026-05-20-004 Unit 1): optional
    ``Callable[[str, dict], None]`` event sink for banner embed
    events.  ``None`` (default) suppresses banner work — preserves
    byte-identical behavior for callers that don't configure
    ``[image_gen]``.
    """
    _lazy_init()
    return dispatch(payload, mode, config, dry_run=dry_run, banner_emit=banner_emit)


def verify_adapter_setup(
    platform: str,
    config: Config,
    *,
    mode: Literal["offline", "live", "dry-run"] = "offline",
    payload: dict[str, Any] | None = None,
) -> VerifyResult | None:
    _lazy_init()
    if mode == "live":
        return _verify_live(platform, config)
    if mode == "dry-run":
        return _verify_dry_run(platform, config, payload or {})
    _verify_offline_setup(platform, config)
    return None


from pathlib import Path as _Path

#: Cache of catalog-derived slugs auto-registered this import.
#: Tests verify registration via this set.
_CATALOG_AUTO_REGISTERED: set[str] = set()


def register_catalog_entries(built_in_dir: str = "", user_config_dir: str = "") -> None:
    """Auto-register catalog YAML entries whose slug is not already claimed.
    Hand-written adapters always win. Tests call with temp dirs."""
    from .catalog.catalog_schema import load_all_entries as _load_catalog_entries
    from .config_driven import ConfigDrivenAdapter as _ConfigDrivenAdapter

    already = set(registered_platforms())
    entries = _load_catalog_entries(built_in_dir=built_in_dir, user_config_dir=user_config_dir)
    for slug, entry in entries.items():
        if slug in already or slug in _CATALOG_AUTO_REGISTERED:
            continue
        register(
            slug,
            _ConfigDrivenAdapter(entry),
            dofollow=entry["dofollow"],
            rationale=entry.get("rationale") or None,
            referral_value=entry.get("referral_value") or None,
        )
        _CATALOG_AUTO_REGISTERED.add(slug)


_builtin_catalog = str(_Path(__file__).resolve().parent / "catalog")
# Rejected origin's addition here (eager `register_catalog_entries(...)` call +
# a second `__all__` list): `_lazy_init()` above already calls
# `register_catalog_entries(built_in_dir=_builtin_catalog)` lazily, and calling
# it again here at module scope would register catalog entries eagerly at
# import time — contradicting this module's own documented design
# (`register_all_adapters()`'s docstring: "importing this module does NOT
# eagerly load any adapter module... only calling this function... triggers
# the full import chain"). A second `__all__` here would also silently
# shadow the complete one already defined near the top of this file (which
# additionally exports Any/Literal/Optional/TYPE_CHECKING) — origin's version
# is missing those.
