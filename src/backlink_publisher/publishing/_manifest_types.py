"""Declarative manifest data types for channel registration.

Plan 2026-05-25-002 Unit 1 — extends ``registry.register()`` with four
declarative metadata kwargs (``ui=``, ``bind=``, ``policy=``,
``visibility=``). The dataclasses defined here are the value types those
kwargs accept.

Design rules (per plan Key Decisions):

- ``frozen=True, slots=True`` — immutable, hashable, no per-instance
  ``__dict__`` overhead; safe to cache and share across requests.
- Declarative only. No methods, no callbacks. Behavioural logic stays
  in adapter / bind backend / WebUI layers.
- Optional everywhere. All current ``register()`` callers pass nothing
  here; new callers opt in field-by-field.
- ``extras: dict[str, Any]`` escape hatch on ``BindDescriptor`` for
  channel-specific fields that don't justify their own column yet
  (per Plan Unit 3 Velog pilot — recipe/selectors module paths).

This module is import-time leaf: it depends only on ``typing`` and
``dataclasses``. ``registry.py`` imports it; nothing in here imports
back. Keeps the legacy import-cycle gymnastics in ``registry.py``
unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Visibility lifecycle states (Plan R7/R8/R9). The four-state enum
# subsumes three orthogonal needs: PR #136's ``HIDDEN_FROM_UI`` set
# (``hidden``), PR #197's "bind-passed filter" (``active`` is the only
# state that appears in publish UI by default), and unverified-dofollow
# rollout (``experimental`` — opt-in only via ``--include-experimental``
# or WebUI advanced mode).
#
# Semantics:
#   active       — default. Listed everywhere, available for publish.
#   experimental — gated behind opt-in flag; bind/publish allowed.
#   hidden       — UI hides it but existing bound configs still work
#                  (PR #136 write.as pattern).
#   retired      — config sections no longer round-tripped by
#                  ``save_config``; publish on existing bound config is
#                  *grace mode* (allowed with WARN log) per Unit 4
#                  deferred decision. Hard cutover left for a future
#                  PR after operator deprecation notice.
Visibility = Literal["active", "experimental", "hidden", "retired"]

# Bind backend identifiers. Open-set; new backends extend the Literal
# at the same PR that adds the backend implementation.
BindBackend = Literal["chrome", "token-paste", "oauth", "cookie", "cdp"]

# Credential-type identifiers for session descriptors.
SessionCredentialType = Literal["cookie", "bearer", "oauth"]

_VISIBILITY_VALUES: frozenset[str] = frozenset(
    ("active", "experimental", "hidden", "retired")
)
_BIND_BACKEND_VALUES: frozenset[str] = frozenset(
    ("chrome", "token-paste", "oauth", "cookie", "cdp")
)


@dataclass(frozen=True, slots=True)
class UiMeta:
    """UI / identity metadata for a channel.

    Replaces hardcoded display strings in templates and the implicit
    "platform name == lowercase display name" assumption that breaks
    for ghpages (display: "GitHub Pages"), devto ("Dev.to"), etc.

    ``icon`` is intentionally a string identifier (e.g.
    ``"bi-globe2"``), not a path — keeps the manifest framework-agnostic
    and lets the template pick rendering strategy.
    """

    display_name: str
    domain: str
    category: str
    icon: str | None = None


@dataclass(frozen=True, slots=True)
class BindDescriptor:
    """One bind backend supported by a channel.

    A channel may support multiple backends (e.g. medium has API token
    and Chrome CDP). The order of ``register(..., bind=[...])`` is the
    UI display order.

    ``card_template`` is the WebUI macro/partial path; ``None`` falls
    back to the default ``_channel_card_macro.html``. ``storage_state_path``
    is a relative template (interpolated with ``BACKLINK_PUBLISHER_CONFIG_DIR``
    at runtime by the bind backend, not here) — store the *shape*, not
    the resolved path.
    """

    backend: BindBackend
    storage_state_path: str | None = None
    login_endpoint: str | None = None
    card_template: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Policy:
    """Throttle / retry / language policy for a channel.

    Numeric defaults live here; env-var override *keys* are declared so
    documentation can enumerate them without grepping. The env-var
    *values* are read at call site by the throttle / retry machinery —
    this dataclass does not perform ``os.getenv``.

    ``language_whitelist`` empty tuple = no restriction. Non-empty =
    only the listed BCP-47 codes are allowed for this channel
    (replaces hardcoded checks in dispatcher per
    ``feedback_target_language_schema_and_dispatcher``).
    """

    throttle_band: tuple[int, int] | None = None
    env_keys: dict[str, str] = field(default_factory=dict)
    retry_id: str = "default"
    liveness_probe_sec: int | None = None
    language_whitelist: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProbeConfig:
    """Describes how to probe a channel's session liveness.

    ``http_method`` defaults to ``"GET"``; use ``"POST"`` with
    ``graphql_query`` for GraphQL endpoints. ``shape`` is a tuple of
    keys to walk into the JSON response — the probe succeeds when the
    final value is non-``None``.
    """

    endpoint: str
    shape: tuple[str, ...] = ()
    http_method: str = "GET"
    graphql_query: str | None = None
    timeout_sec: int = 10
    headers: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class RefreshConfig:
    """Describes how to refresh an expiring credential.

    ``method="cookie-implicit"`` means the channel refreshes auth via
    ``Set-Cookie`` on normal requests (no explicit refresh action).
    ``method="oauth-refresh-token"`` means a POST to ``token_endpoint``
    with ``grant_type=refresh_token``.
    """

    method: str  # "cookie-implicit" | "oauth-refresh-token"
    token_endpoint: str | None = None
    expiration_window_sec: int = 300


@dataclass(frozen=True, slots=True)
class SessionDescriptor:
    """Describes a channel's credential lifecycle.

    ``credential_type`` selects the auth-apply strategy (cookie vs bearer).
    ``config_path`` is a template path (``<config_dir>/…``) resolved at
    runtime. ``probe`` and ``refresh`` are optional — channels without
    live-probe or refresh support omit the corresponding config.
    """

    credential_type: SessionCredentialType
    config_path: str = ""
    probe: ProbeConfig | None = None
    refresh: RefreshConfig | None = None
