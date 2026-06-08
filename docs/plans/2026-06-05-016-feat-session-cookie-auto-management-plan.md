---
title: "feat: session cookie auto-management — shared SessionManager + CredentialProvider"
type: feat
status: completed
date: 2026-06-05
origin: docs/brainstorms/2026-06-05-session-cookie-auto-management-requirements.md
claims:
  paths:
    - src/backlink_publisher/publishing/session/__init__.py
    - src/backlink_publisher/publishing/session/manager.py
    - src/backlink_publisher/publishing/session/credential.py
    - src/backlink_publisher/publishing/session/provider.py
    - src/backlink_publisher/publishing/_manifest_types.py
    - src/backlink_publisher/publishing/registry.py
    - src/backlink_publisher/publishing/_registry_manifest.py
    - src/backlink_publisher/publishing/_manifests.py
    - src/backlink_publisher/publishing/adapters/velog_graphql.py
    - src/backlink_publisher/publishing/adapters/medium_api.py
    - src/backlink_publisher/publishing/adapters/blogger_api.py
  shas: []
---

# Session Cookie 自動管理 — Implementation Plan

## Summary

一個共用的 `SessionManager` 元件，為所有 publisher adapter 提供統一的 credential 生命週期管理。Adapter 透過 `get_session(channel)` 取得有效 `requests.Session`；SessionManager 負責載入 credential → lazily probe 有效性 → 過期時自動 refresh → refresh 失敗時拋 `AuthExpiredError` 並標記 channel expired。平台差異（credential 類型、probe endpoint、refresh 方式）透過 declarative metadata 描述，不須 per-platform strategy code。

**Override decision — Blogger OAuth refresh model (2026-06-05):** 方案A confirmed — SessionManager 通用 refresh POST 取代 `google-auth` 函式庫。Blogger adapter 從 `googleapiclient` 遷移到原生 `requests.Session`，與其他 adapter 一致。

---

## 1. Problem & Context

### 1.1 現狀

三個主要 adapter（Velog、Medium、Blogger）各自處理 credential 生命週期，pattern 差異極大：

| 面向 | Velog | Medium | Blogger |
|---|---|---|---|
| Credential 類型 | Cookie (storage-state.json) | Bearer token (OAuth/Integration Token) | OAuth (google-auth Credentials) |
| 載入方式 | `_load_cookies()` 自讀 JSON | `_resolve_medium_token_data()` 三級優先級 | `_build_credentials()` google-auth 流程 |
| Probe | `_probe_session_alive()` GraphQL currentUser | `_fetch_medium_user_id()` GET /me | 無 — 靠 401 發現 |
| Refresh | Set-Cookie 隱式 capture | OAuth refresh_token (config 層) | `creds.refresh(Request())` + lock |
| 錯誤處理 | AuthExpiredError (無統一介面) | AuthExpiredError | AuthExpiredError |

### 1.2 目標

- 所有 adapter 透過 `get_session(channel)` 取 session，不直接讀檔或管理 refresh
- 信用證載入/probe/refresh/錯誤處理集中在 SessionManager
- 平台差異透過 declarative metadata 描述（擴展現有 `_manifest_types.py` 模式）
- 新增 cookie-based 平台時不需重寫 credential 管理

### 1.3 Scope Boundaries

- 不包含背景週期性 probe — 只做 publish 前 lazy probe
- 不包含 session pool / 多 session 切換
- 不修改現有 bind-channel 流程
- 不包含自動重試 refresh
- 不包含 credential rotation 或自動 re-binding
- 不統一現有 cookie / token file 格式
- 不包含 `_util/http_session.py` 的改造

---

## 2. Component Architecture

### 2.1 新增檔案

```
src/backlink_publisher/publishing/session/
├── __init__.py        # 公開介面: get_session(), invalidate_session(), init_session_manager()
├── manager.py         # SessionManager 類別
├── credential.py      # Credential / CredentialBundle 型別
└── provider.py        # CredentialProvider 介面 + DefaultCredentialProvider
```

### 2.2 修改檔案

| 檔案 | 修改內容 |
|---|---|
| `_manifest_types.py` | 新增 `SessionDescriptor` / `ProbeConfig` / `RefreshConfig` dataclasses |
| `registry.py` | `register()` 新增 `session=` kwarg + validation + `_SESSION_BY_PLATFORM` dict |
| `_registry_manifest.py` | 新增 `session()` accessor |
| `_manifests.py` | Velog/Medium/Blogger MANIFEST 加入 `session=` |
| `velog_graphql.py` | 移除 `_load_cookies`, `_extract_tokens_from_origins`, `_probe_session_alive`; 改用 `get_session("velog")` |
| `medium_api.py` | 移除 `_resolve_medium_token_data`, `_check_medium_token_expiry`; 改用 `get_session("medium")` |
| `blogger_api.py` | 移除 `_build_credentials`, `_near_expiry`, `_refresh_lock`, `json_from_creds`, google-auth 依賴; 改用 `get_session("blogger")` + Blogger REST API 直調 |

### 2.3 架構圖

```
┌─────────────────────────────────────────────────┐
│                  SessionManager                   │
│                                                   │
│  get_session(channel)                             │
│    ├─ CredentialProvider.load(channel) → Credential│
│    ├─ requests.Session() + apply_credential()    │
│    ├─ probe(session, channel_meta)               │
│    │  ├─ 成功 → return session                   │
│    │  └─ 失敗 → refresh() → retry probe          │
│    │       ├─ 成功 → save + return               │
│    │       └─ 失敗 → AuthExpiredError             │
│  invalidate_session(channel)                      │
├─────────────────────────────────────────────────┤
│              CredentialProvider                    │
│  Interface: load(channel), save(channel, cred)    │
│  DefaultImpl: 讀寫既有 credential file 格式         │
└─────────────────────────────────────────────────┘
         ▲                    ▲
         │                    │
    register session=     get_session("velog")
    metadata                    │
    ┌──────────────┐    ┌──────┴──────┐
    │   Manifests   │    │   Adapters   │
    │  velog: cookie│    │  VelogGraphQL│
    │ medium: bearer│    │  MediumAPI   │
    │ blogger: oauth│    │  BloggerAPI  │
    └──────────────┘    └─────────────┘
```

---

## 3. Detailed Design

### 3.1 Credential 型別 (`session/credential.py`)

```python
@dataclass
class Credential:
    """Unified credential container for a channel session.

    One and only one of ``cookies`` / ``header_value`` is populated,
    depending on ``auth_type``.
    """
    auth_type: Literal["cookie", "bearer", "oauth"]

    # Cookie auth (velog)
    cookies: dict[str, str] | None = None          # name → value

    # Bearer / OAuth access token (medium, blogger)
    header_value: str | None = None                # raw token
    header_format: str = "Bearer {}"               # e.g. "Bearer {token}"

    # OAuth refresh fields (blogger — also medium OAuth)
    refresh_token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    token_uri: str | None = None
    scopes: list[str] | None = None
    expiry: float | None = None                    # unix timestamp
```

Rationale: 單一 dataclass 而非多個 subtype，因為 SessionManager 的處理邏輯對所有 auth_type 相同（apply → probe → refresh），差異只在 metadata 層面表達。

### 3.2 CredentialProvider 介面 (`session/provider.py`)

```python
class CredentialProvider(ABC):
    @abstractmethod
    def load(self, channel: str) -> Credential:
        """Load credential for *channel*.

        Raises DependencyError if credential file not found or unreadable.
        """
        ...

    @abstractmethod
    def save(self, channel: str, credential: Credential) -> None:
        """Persist updated credential (after refresh).

        No-op for channels that don't need to persist refreshed tokens.
        """
        ...
```

```python
class DefaultCredentialProvider(CredentialProvider):
    """Reads existing credential files in their current format.

    Path resolution: ``config_dir / "{channel}-token.json"`` or
    config field (e.g. ``config.velog.cookies_path``).
    """

    def __init__(self, config: Config):
        self._config = config

    def load(self, channel: str) -> Credential:
        if channel == "velog":
            return self._load_velog()
        elif channel == "medium":
            return self._load_medium()
        elif channel == "blogger":
            return self._load_blogger()
        raise DependencyError(f"Unknown channel: {channel}")

    def save(self, channel: str, credential: Credential) -> None:
        if channel == "blogger":
            self._save_blogger(credential)
        # Velog: cookies captured by requests.Session (Set-Cookie)
        # Medium: OAuth token saved by config layer, not by SessionManager

    def _load_velog(self) -> Credential:
        """Load from velog-cookies.json / storage-state.json (migrate from
        existing ``_load_cookies()``, same logic, same 0600 check)."""
        ...

    def _load_medium(self) -> Credential:
        """Load with priority: OAuth access_token → Integration Token → TOML.
        Migrate from existing ``_resolve_medium_token_data()``."""
        ...

    def _load_blogger(self) -> Credential:
        """Load from blogger-token.json, parse into full OAuth Credential.
        Migrate from ``load_blogger_token()`` + ``Credentials.from_authorized_user_info()``."""
        ...

    def _save_blogger(self, credential: Credential) -> None:
        """Save updated OAuth token after refresh.
        Migrate from ``save_blogger_token(json_from_creds(creds), ...)``."""
        ...
```

### 3.3 SessionManager (`session/manager.py`)

```python
class SessionManager:
    """Manages credential lifecycle for publisher channels.

    Cache strategy: one session per channel, invalidated on refresh failure.
    Concurrency: simple lock-free for now (sequential publish per channel).
    """

    def __init__(self, credential_provider: CredentialProvider):
        self._provider = credential_provider
        self._sessions: dict[str, requests.Session] = {}
        self._channel_meta: dict[str, SessionDescriptor | None] = {}

    def get_session(self, channel: str) -> requests.Session:
        """Return a valid ``requests.Session`` for *channel*.

        Flow:
        1. Cached session exists + probe OK → return cached
        2. Load credential via CredentialProvider
        3. Create fresh ``requests.Session`` + apply credential
        4. Probe (if ProbeConfig configured)
        5. Probe OK → cache + return
        6. Probe FAIL + has RefreshConfig → refresh credential
           a. POST refresh (OAuth) or re-probe (Set-Cookie)
           b. Save new credential via provider
           c. Create fresh session + apply
           d. Probe again
           e. Probe OK → cache + return
        7. All fail → AuthExpiredError + mark_expired
        """
        ...

    def invalidate_session(self, channel: str) -> None:
        """Force next ``get_session`` to reload from scratch."""
        self._sessions.pop(channel, None)
```

#### 3.3.1 Probe Logic

```python
def _probe(self, session: requests.Session, channel: str) -> bool:
    """Lightweight liveness check. Returns True if session is valid."""
    meta = get_channel_metadata(channel)  # from registry
    probe_cfg = meta.session.probe if meta and meta.session else None
    if probe_cfg is None:
        return True  # no probe configured — trust the credential

    try:
        if probe_cfg.method == "POST" and probe_cfg.body:
            resp = session.post(probe_cfg.endpoint, json=probe_cfg.body,
                                headers=probe_cfg.headers, timeout=_PROBE_TIMEOUT)
        else:
            resp = session.get(probe_cfg.endpoint,
                               headers=probe_cfg.headers, timeout=_PROBE_TIMEOUT)
    except requests.RequestException:
        return False  # network error → treat as probe failure

    if resp.status_code != probe_cfg.expected_status:
        return False

    if probe_cfg.expected_body_path and probe_cfg.expected_body_path != "":
        # Simple dot-path check: "data.currentUser.id" → check nested key exists
        data = resp.json()
        if not _get_by_dot_path(data, probe_cfg.expected_body_path):
            return False

    return True
```

#### 3.3.2 Refresh Logic

```python
def _refresh(self, credential: Credential, channel: str) -> Credential:
    """Refresh credential in place. Returns updated Credential."""
    meta = get_channel_metadata(channel)
    refresh_cfg = meta.session.refresh if meta and meta.session else None
    if refresh_cfg is None:
        raise AuthExpiredError(channel=channel,
                               reason="No refresh configured")

    if credential.auth_type == "oauth":
        return self._refresh_oauth(refresh_cfg, credential, channel)
    elif credential.auth_type == "cookie" and refresh_cfg.uses_implicit_capture:
        return self._refresh_cookie_implicit(credential, channel)
    raise AuthExpiredError(channel=channel,
                           reason=f"Unsupported refresh for {credential.auth_type}")

def _refresh_oauth(self, cfg: RefreshConfig, cred: Credential, channel: str) -> Credential:
    """POST ``grant_type=refresh_token`` to token_uri."""
    resp = requests.post(
        cred.token_uri or cfg.endpoint,
        data={
            "grant_type": "refresh_token",
            "refresh_token": cred.refresh_token,
            "client_id": cred.client_id,
            "client_secret": cred.client_secret,
        },
        timeout=_REFRESH_TIMEOUT,
    )
    if not resp.ok:
        raise AuthExpiredError(channel=channel,
                               reason=f"OAuth refresh failed: HTTP {resp.status_code}")
    data = resp.json()
    return Credential(
        auth_type="oauth",
        header_value=data["access_token"],
        refresh_token=data.get("refresh_token", cred.refresh_token),
        client_id=cred.client_id,
        client_secret=cred.client_secret,
        token_uri=cred.token_uri,
        expiry=time.time() + data.get("expires_in", 3600),
    )
```

### 3.4 公開介面 (`session/__init__.py`)

```python
"""Shared SessionManager — get a valid ``requests.Session`` for any channel."""

from .manager import SessionManager
from .provider import CredentialProvider, DefaultCredentialProvider

_session_manager: SessionManager | None = None

def init_session_manager(config: Config) -> None:
    global _session_manager
    _session_manager = SessionManager(DefaultCredentialProvider(config))

def get_session(channel: str) -> requests.Session:
    if _session_manager is None:
        raise RuntimeError("SessionManager not initialized")
    return _session_manager.get_session(channel)

def invalidate_session(channel: str) -> None:
    if _session_manager is not None:
        _session_manager.invalidate_session(channel)
```

### 3.5 Declarative Metadata (`_manifest_types.py`)

```python
@dataclass(frozen=True, slots=True)
class ProbeConfig:
    """Lightweight liveness/expiry check for a channel session.

    ``expected_body_path`` is a dot-delimited JSON key path
    (e.g. ``"data.currentUser.id"``). Empty string = check only
    HTTP status.
    """
    endpoint: str
    method: str = "GET"
    expected_status: int = 200
    expected_body_path: str = ""
    headers: dict[str, str] | None = None
    body: dict[str, Any] | None = None               # for GraphQL probes


@dataclass(frozen=True, slots=True)
class RefreshConfig:
    """Credential refresh configuration.

    ``endpoint`` is the OAuth token_uri (only used for ``oauth`` type).
    ``uses_implicit_capture`` = True for cookie auth where the
    ``requests.Session`` automatically captures ``Set-Cookie`` from any
    response (no explicit refresh URL needed).
    """
    endpoint: str | None = None
    grant_type: str = "refresh_token"
    uses_implicit_capture: bool = False


@dataclass(frozen=True, slots=True)
class SessionDescriptor:
    """Session/credential lifecycle metadata for a channel.

    Designed as an opt-in extension of ``register()`` — backward
    compatible: all existing ``register()`` callers pass ``None``
    (default) and are unaffected.
    """
    credential_type: Literal["cookie", "bearer", "oauth"]
    probe: ProbeConfig | None = None
    refresh: RefreshConfig | None = None
```

### 3.6 Registry Extension (`registry.py`)

```python
from ._manifest_types import SessionDescriptor

_SESSION_BY_PLATFORM: dict[str, SessionDescriptor] = {}

def register(
    ...,
    session: SessionDescriptor | None = None,
    ...
) -> None:
    # ... existing validation ...
    if session is not None and not isinstance(session, SessionDescriptor):
        raise RegistryError(
            f"`register({platform!r}, ..., session=...)` — expected "
            f"SessionDescriptor, got {type(session).__name__}."
        )
    _SESSION_BY_PLATFORM[platform] = session
    # ... existing RegistryEntry construction ...

def session(platform: str) -> SessionDescriptor | None:
    """Return session metadata for *platform*, or None."""
    return _SESSION_BY_PLATFORM.get(platform)
```

### 3.7 Manifest Declarations (`_manifests.py`)

```python
from .._manifest_types import SessionDescriptor, ProbeConfig, RefreshConfig

VELOG_MANIFEST = dict(
    # ... existing ...
    session=SessionDescriptor(
        credential_type="cookie",
        probe=ProbeConfig(
            endpoint="https://v2.velog.io/graphql",
            method="POST",
            expected_status=200,
            expected_body_path="data.currentUser.id",
            body={"query": "{ currentUser { id username } }"},
            headers={
                "accept": "*/*",
                "content-type": "application/json",
                "origin": "https://velog.io",
                "referer": "https://velog.io/",
            },
        ),
        refresh=RefreshConfig(uses_implicit_capture=True),
    ),
)

MEDIUM_MANIFEST = dict(
    # ... existing ...
    session=SessionDescriptor(
        credential_type="bearer",
        probe=ProbeConfig(
            endpoint="https://api.medium.com/v1/me",
            method="GET",
            expected_status=200,
        ),
        refresh=None,  # integration token doesn't expire;
                        # OAuth refresh is handled by generic OAuth flow
    ),
)

# For OAuth platform (Blogger) — used only if the adapter migrates to
# native REST (方案A). If kept on googleapiclient, session=None.
# 方案A confirmed 2026-06-05.
BLOGGER_MANIFEST = dict(
    # ... existing ...
    session=SessionDescriptor(
        credential_type="oauth",
        probe=ProbeConfig(
            endpoint="https://www.googleapis.com/oauth2/v3/tokeninfo",
            method="GET",
            expected_status=200,
        ),
        refresh=RefreshConfig(
            endpoint="https://oauth2.googleapis.com/token",
            grant_type="refresh_token",
        ),
    ),
)
```

**Google tokeninfo endpoint note:** `GET https://www.googleapis.com/oauth2/v3/tokeninfo?access_token={token}` returns token metadata for any valid Google OAuth token. It's a lightweight auth-probe that works regardless of OAuth scopes. 200 = valid, 400/401 = expired. The SessionManager applies the token as Bearer header — for this specific probe, we pass the token as query param instead (handled by ProbeConfig logic: if method=GET and no Authorization header works, the body/param template can include the token). **At implementation time, verify this endpoint still works in 2026 without OAuth scope issues.** If deprecated, fall back to `GET https://blogger.googleapis.com/v3/blogs/byurl?url=test.blogspot.com` (but this is public, not auth-gated).

---

## 4. Implementation Units

### Unit 1 — Metadata & Types (1 PR, ~50 SLOC)

**Files:**
- `_manifest_types.py`: Add `SessionDescriptor`, `ProbeConfig`, `RefreshConfig`
- `registry.py`: Add `session=` kwarg to `register()`, `_SESSION_BY_PLATFORM` dict, `session()` accessor, validation

**Acceptance:**
- `register("test", FakeAdapter, dofollow=True, session=SessionDescriptor(credential_type="bearer"))` works
- `register("test2", FakeAdapter, dofollow=True)` without `session=` works (backward compat)
- Invalid session type raises `RegistryError`
- `session("test")` returns the descriptor; `session("nonexistent")` returns `None`

**Isolation:** No adapter changes — safe standalone PR, zero behavioral impact.

### Unit 2 — CredentialProvider (1 PR, ~150 SLOC)

**Files:**
- `session/__init__.py`: Package init, re-exports
- `session/credential.py`: `Credential` dataclass
- `session/provider.py`: `CredentialProvider` ABC + `DefaultCredentialProvider`

**CredentialProvider migration notes:**

**Velog `_load_cookies()`:**
- Move the storage-state.json parsing into `DefaultCredentialProvider._load_velog()`
- Keep the same logic: `velog-cookies.json` → 0600 check → cookies list → `_extract_tokens_from_origins` fallback
- Return `Credential(auth_type="cookie", cookies=...)`

**Medium `_resolve_medium_token_data()`:**
- Move the three-level priority chain into `DefaultCredentialProvider._load_medium()`
- OAuth access_token → `Credential(auth_type="bearer", header_value=..., refresh_token=..., expiry=...)`
- Integration Token / TOML → `Credential(auth_type="bearer", header_value=...)` (no refresh)

**Blogger `load_blogger_token()` + OAuth parsing:**
- Move into `DefaultCredentialProvider._load_blogger()`
- Read `blogger-token.json`, extract fields → `Credential(auth_type="oauth", header_value=token, refresh_token=..., client_id=..., etc.)`
- `_save_blogger()` writes updated token file (same format as current `save_blogger_token()`)

**No adapter changes yet** — adapters continue using their own credential loading code
until Unit 4. The provider is wired to SessionManager only.

### Unit 3 — SessionManager Core (1 PR, ~120 SLOC)

**Files:**
- `session/manager.py`: `SessionManager` class
- `session/__init__.py`: `init_session_manager()`, `get_session()`, `invalidate_session()` public API

**Acceptance (integration test with mock provider):**
1. Mock `CredentialProvider` returns valid credential → `get_session("test")` returns session with probe OK
2. Mock probe fails → SessionManager calls refresh → new credential applied → probe OK → returns session
3. Mock refresh fails → `AuthExpiredError` raised
4. No probe configured → returns session immediately
5. `invalidate_session("test")` → next `get_session` does fresh load

**Note:** Unit 3 operates standalone — no adapter uses it yet. Good for testing isolation.

### Unit 4 — Velog Adapter Migration (1 PR, ~100 SLOC net removal)

**Files:**
- `_manifests.py`: Add `session=SessionDescriptor(...)` to `VELOG_MANIFEST`
- `velog_graphql.py`: Remove `_load_cookies()`, `_extract_tokens_from_origins()`, `_probe_session_alive()`, `_mask_cookies()`, `_TOKEN_FIELDS`, `_PROBE_QUERY`, `_PROBE_TIMEOUT`; replace `cookies = _load_cookies(...)` / `session = requests.Session()` / `session.cookies.update(cookies)` with `session = get_session("velog")`
- `publish-backlinks` entrypoint or dispatch init: call `init_session_manager(config)` before adapter loop

**Adapter changes:**
```python
# Before (velog_graphql.py publish())
cookies_path = config.config_dir / "velog-cookies.json"
cookies = _load_cookies(cookies_path)
session = requests.Session()
session.cookies.update(cookies)

# After
from backlink_publisher.publishing.session import get_session
session = get_session("velog")
```

**Velog uniqueness:** The `requests.Session` for velog must carry `_VELOG_REQUIRED_HEADERS`. These are publish-level headers (content-type, origin, referer), not credential-level. They should stay in the adapter. The SessionManager sets cookies; the adapter adds headers before making API calls.

**Keep in adapter:** `_VELOG_REQUIRED_HEADERS`, `_VELOG_UA`, `_VELOG_GRAPHQL_ENDPOINT`, rate-limit lock/count logic, `_execute_write_post()`, `_handle_null_write_post()`, `_apply_publish_jitter()`, `_slugify()`, `embed_banner()`, banner publishing logic, link_attr verification.

### Unit 5 — Medium Adapter Migration (1 PR, ~80 SLOC net removal)

**Files:**
- `_manifests.py`: Add `session=SessionDescriptor(...)` to `MEDIUM_MANIFEST`
- `medium_api.py`: Remove `_resolve_medium_token_data()`, `_check_medium_token_expiry()`; replace header construction with `get_session("medium")`; migrate `http_get`/`http_post` calls to `session.get()`/`session.post()`

```python
# Before
token, medium_token_data = _resolve_medium_token_data(config)
_check_medium_token_expiry(medium_token_data)
headers = {"Authorization": f"Bearer {token}", ...}
user_id = _fetch_medium_user_id(headers)

# After
from backlink_publisher.publishing.session import get_session
session = get_session("medium")
session.headers.update({...})  # Content-Type, Accept, etc.
user_id = _fetch_medium_user_id_via_session(session)
```

**Note on `http_get`/`http_post` replacement:** Medium currently uses wrapper functions from `backlink_publisher.http`. These accept `headers`, `json`, `timeout` args and return `requests.Response`. Migration path: switch to `session.get()` / `session.post()` with the same arguments. The `_fetch_medium_user_id()` and `_create_medium_post()` helpers need their internal calls updated from `http_get(...)` / `http_post(...)` to `session.get(...)` / `session.post(...)`. Keep the existing retry logic patterns.

### Unit 6 — Blogger Adapter Migration — 方案A (1 PR, ~200 SLOC net removal)

**This is the largest change.** Replaces google-auth OAuth + googleapiclient with generic OAuth refresh + native REST API calls.

**Files:**
- `_manifests.py`: Add `session=SessionDescriptor(...)` to `BLOGGER_MANIFEST`
- `blogger_api.py`: Major rewrite of `publish()` method

**Remove:**
- `_build_credentials()` — entire function
- `_near_expiry()` — entire function
- `_refresh_lock()` — entire context manager
- `json_from_creds()` — entire function
- Imports: `google.oauth2.credentials`, `google.auth.transport.requests`, `google_auth_oauthlib.flow`, `googleapiclient.discovery`, `googleapiclient.errors`
- `fcntl` import (unless still needed)

**Add:**
```python
from backlink_publisher.publishing.session import get_session

def publish(self, payload, mode, config):
    session = get_session("blogger")
    blog_id = resolve_blog_id(config, payload.get("main_domain", ""))

    content_html = extract_publish_html(payload, "blogger")
    canonical = payload.get("seo", {}).get("canonical_url") or None
    if canonical:
        content_html = f'<link rel="canonical" href="{canonical}">\n{content_html}'

    body = {
        "title": payload.get("title", ""),
        "content": content_html,
        "labels": payload.get("tags", [])[:20],
    }

    is_draft = mode == "draft"
    url = f"https://blogger.googleapis.com/v3/blogs/{blog_id}/posts/"

    # For draft: ?isDraft=true, for publish: no isDraft
    params = {"isDraft": "true"} if is_draft else {}

    def _do_post():
        resp = session.post(url, json=body, params=params, timeout=30)
        if resp.status_code in RETRYABLE_HTTP_STATUSES:
            raise _TransientHTTPError(resp.status_code)
        if resp.status_code == 401:
            raise AuthExpiredError(channel="blogger",
                                   reason="Blogger HTTP 401")
        if not resp.ok:
            raise ExternalServiceError(
                f"Blogger API error HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    result = retry_transient_call(
        _do_post,
        is_retryable=lambda exc: isinstance(exc, _TransientHTTPError),
        adapter="blogger-api",
    )

    url = result.get("url", "")
    ...
```

**Keep:** `embed_banner()` (base64 inlining, no credential involvement), `extract_publish_html()`, canonical URL prepend, `AdapterResult` construction.

**Dependency changes:** Remove `google-api-python-client`, `google-auth`, `google-auth-oauthlib` from `pyproject.toml` (verify nothing else depends on them).

### Unit 7 — Init Hook (trivial, ~15 SLOC)

Find the publish dispatch entry point where adapters are called and add `init_session_manager(config)` before the adapter loop.

The init call should go in `dispatch()` in `registry.py` (lazy one-time init) or in `publish()` in `adapters/__init__.py`. Best location: in `dispatch()`, check if SessionManager is initialized; if not, init with the first config it receives. This avoids changing CLI entry points.

```python
# In registry.py dispatch() — add at function beginning:
from backlink_publisher.publishing.session import init_session_manager, \
    _session_manager
if _session_manager is None:
    init_session_manager(config)
```

---

## 5. Test Strategy

### 5.1 Unit Tests

| Test | What | Coverage |
|---|---|---|
| `test_session_manager_get_session` | Happy path — mock provider returns valid credential, probe succeeds | R1, R2 |
| `test_session_manager_probe_and_refresh` | Mock probe fails → refresh succeeds → returns session | R3, R4 |
| `test_session_manager_refresh_failure` | Mock refresh fails → AuthExpiredError | R5 |
| `test_session_manager_no_probe` | SessionDescriptor has no probe → skip probe, return session | R3 variation |
| `test_session_manager_invalidate` | Cache cleared → next get_session re-loads | R6 |
| `test_session_manager_cache_hit` | Second get_session reuses cached session (no probe) | implicit |
| `test_credential_provider_load_velog` | Fixture storage-state.json → correct Credential | R7, R10, R15 |
| `test_credential_provider_load_medium_token` | Fixture OAuth token → correct Credential | R7, R11, R16 |
| `test_credential_provider_load_blogger` | Fixture blogger-token.json → correct Credential | R7, R9, R17 |
| `test_credential_provider_0600_check` | Non-0600 file → DependencyError | R10 (permission) |
| `test_register_session_descriptor` | register() with session= → stored and retrievable | R12, R13 |
| `test_register_backward_compat` | register() without session= → no error | R12 |
| `test_session_descriptor_frozen` | SessionDescriptor is frozen+slots | type safety |
| `test_oauth_refresh_post` | Valid OAuth refresh → returns updated Credential | R17 |
| `test_all_auth_types_probe` | cookie/bearer/oauth all probe correctly | R15, R16, R17 |

### 5.2 Migration Tests (per unit)

| Test | What |
|---|---|
| `test_velog_adapter_with_session_manager` | Velog publish works with get_session replacing _load_cookies |
| `test_medium_adapter_with_session_manager` | Medium publish works with get_session replacing _resolve_medium_token_data |
| `test_blogger_adapter_with_session_manager` | Blogger publish works with get_session + native REST replacing googleapiclient |

### 5.3 Integration / E2E

| Test | What |
|---|---|
| `test_session_to_publish_flow` | Mock dispatcher with SessionManager — full publish cycle |
| `test_expired_channel_marked` | AuthExpiredError → mark_expired called correctly |

### 5.4 Regressions

| Test | Why |
|---|---|
| `test_adapter_dofollow_gate.py` | register() signature unchanged for non-session kwargs |
| `test_manifest_contract.py` | Manifest shape still passes contract after SessionDescriptor addition |
| `test_no_monolith_regrowth.py` | Verify velog/medium/blogger SLOC reductions don't push other files over ceiling |

### 5.5 Blogger 方案A Verification

| Check | Method |
|---|---|
| Blogger API v3 `posts.insert` REST contract | Sample HTTP request via curl against scratch blog before writing code |
| Blogger OAuth2 token refresh | Verify `POST https://oauth2.googleapis.com/token` returns expected shape |
| Google tokeninfo endpoint availability | Verify `GET https://www.googleapis.com/oauth2/v3/tokeninfo?access_token=TOKEN` returns 200/401 as expected |
| blogger-token.json format | Read existing file format before implementing _save_blogger |

---

## 6. Key Decisions (pre-verified by brainstorm)

| Decision | Choice | Rationale |
|---|---|---|
| Shared SessionManager | Yes — single component | Reduces duplication across adapters |
| Lazy probe | Yes — before publish | Simpler than background polling |
| CredentialProvider interface | Yes — abstract | Loose coupling, testable |
| Declarative metadata | Yes — extend _manifest_types.py | Follows existing pattern |
| Refresh failure = no retry | Yes — AuthExpiredError | Race prevention, clean fail |
| Blogger google-auth → generic OAuth | 方案A — SessionManager handles | Full uniformity, remove 3 deps |
| Session commit plan | One PR per unit | Isolated, testable, revertable |
| SessionManager init | Lazy in dispatch() | No CLI entry point changes |
| Probe endpoint per channel | Metadata | Flexible per platform needs |

---

## 7. Dependencies & Assumptions

- Google OAuth2 token endpoint `https://oauth2.googleapis.com/token` follows standard RFC 6749 `grant_type=refresh_token` — confirmed by google-auth library source behavior (it does exactly this POST internally).
- Google OAuth2 tokeninfo endpoint works without additional scopes — **verify at implementation time**.
- Blogger REST API `POST /v3/blogs/{blogId}/posts` has same contract as googleapiclient wrapper — **verify via curl before coding**.
- Medium API v1 `GET /me` continues to return 200 for valid tokens and 401 for expired ones.
- Velog's `currentUser` GraphQL query continues to be the auth probe endpoint.
- `requests.Session` in Velog continues to auto-capture `Set-Cookie` (standard HTTP behavior, stable).

---

## 8. Rollout / Migration

### Unit Order & Dependencies

```
Unit 1 (Types) ──→ Unit 2 (Provider) ──→ Unit 3 (Manager)
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
             Unit 4 (Velog)           Unit 5 (Medium)           Unit 6 (Blogger)
                    │                         │                         │
                    └─────────────────────────┼─────────────────────────┘
                                              ▼
                                       Unit 7 (Init)
```

Unit 1-3 are prerequisites. Unit 4/5/6 can be done in parallel (different files, no overlap). Unit 7 is the final hook-up.

### Backward Compatibility

- All non-session adapters (20+ channels in `adapters/__init__.py`) pass `session=None` (default) — zero behavioral change.
- Existing tests for velog/medium/blogger still pass after Unit 4/5/6 (the internal logic changes but the public `publish()` contract is identical).
- The `register()` signature extension is backward compatible — old callers don't need to change.

### Cleanup

After all units:
- Verify no remaining references to removed functions (`_load_cookies`, `_build_credentials`, etc.)
- Verify `google-api-python-client`, `google-auth`, `google-auth-oauthlib` can be safely removed from `pyproject.toml`
- Remove dead imports in `blogger_api.py` (`fcntl`, `random`, `datetime`, etc. if no longer used)
