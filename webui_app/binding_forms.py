"""Binding-form presentation schemas for the SPA settings channel section.

Plan 2026-06-18-002 U7 (Settings section 3, slice 2 — binding forms). Pure,
flask-free presentation metadata for the credential-binding forms the SPA renders
for the four FIXED-credential auth types (``token`` / ``token_fields`` /
``paste_blob`` / ``userpass``).

The form FIELD NAMES are NOT defined here. They are read from the single source
the SAVE path itself uses — ``services.credential_service``'s dispatch maps — so a
field the SPA renders is exactly a field ``ChannelBindAPI.save_channel_credential``
will persist. ``test_webui_api_v1_channel_forms.py`` asserts that parity. Only the
PRESENTATION (label / input type / placeholder / help text / secret flag) lives
here: the same labels the legacy Jinja ``_settings_binding_*`` partials carry,
ported so the SPA matches until U8 retires those templates. Duplicating the labels
(not the field names, which stay single-sourced) is a deliberate, short-lived
overlap — the Jinja copy is deleted with the rest of the legacy page in U8.

``oauth`` / ``live_browser`` / ``anon`` channels have no fixed-credential form here:
Blogger OAuth and the medium/velog browser-login flows are card actions handled in a
later slice; anon channels need no credentials at all.
"""

from __future__ import annotations

# Generic presentation for the single-shape auth types (token / userpass /
# paste_blob), keyed by the (fixed) field name those forms post.
_GENERIC_FIELDS: dict[str, dict] = {
    "token": {
        "label": "Token / API Key",
        "type": "password",
        "placeholder": "粘贴 API Token",
        "help": "写入 ~/.config/backlink-publisher/ 下的 0600 token 文件。空白表示保留现有值。",
    },
    "username": {
        "label": "用户名",
        "type": "text",
        "placeholder": "登录用户名",
        "help": "",
    },
    "password": {
        "label": "密码",
        "type": "password",
        "placeholder": "登录密码",
        "help": "用户名和密码必须同时填写才会更新；空白表示保留现有凭据。",
    },
    "blob": {
        "label": "Cookie JSON",
        "type": "textarea",
        "placeholder": '{"cookies": [{"name": "...", "value": "...", "domain": "..."}]}',
        "help": '需包含 {"cookies": [...]} 外层结构，单项必须有 name / value / domain 字段。',
    },
}

# Per-channel presentation for ``token_fields`` channels, keyed by field name.
# Ported verbatim (labels/types/placeholders/help) from the Jinja
# _settings_binding_token_fields / _settings_channel_token_paste partials. devto
# (auth_type ``token``) uses the generic ``token`` entry; notion has its own SPA
# card (no entry here); ghpages is folded into the workbench with its own labels.
_TOKEN_FIELDS_PRESENTATION: dict[str, dict[str, dict]] = {
    "ghpages": {
        "token": {"label": "GitHub PAT", "type": "password", "placeholder": "ghp_...",
                  "help": "GitHub → Settings → Developer settings → PAT，需 repo（contents:write）权限以推送到 Pages 仓库。"},
    },
    "wordpresscom": {
        "token": {
            "label": "Access Token", "type": "password",
            "placeholder": "粘贴 WordPress.com OAuth Access Token",
            "help": "来自 WordPress.com 开发者应用授权后的 access_token。",
        },
        "site": {
            "label": "Site URL", "type": "url",
            "placeholder": "https://yoursite.wordpress.com",
            "help": "您的 WordPress.com 站点地址（须 https://）。",
        },
    },
    "tumblr": {
        "consumer_key": {"label": "Consumer Key", "type": "password",
                         "placeholder": "Tumblr OAuth Consumer Key", "help": "Tumblr App → Consumer Key。"},
        "consumer_secret": {"label": "Consumer Secret", "type": "password",
                            "placeholder": "Tumblr OAuth Consumer Secret", "help": "Tumblr App → Consumer Secret。"},
        "oauth_token": {"label": "OAuth Token", "type": "password",
                        "placeholder": "OAuth Access Token", "help": "授权后获得的 OAuth Token。"},
        "oauth_token_secret": {"label": "OAuth Token Secret", "type": "password",
                               "placeholder": "OAuth Token Secret", "help": "授权后获得的 OAuth Token Secret。"},
        "blog_identifier": {"label": "Blog Identifier", "type": "text",
                            "placeholder": "yourblog.tumblr.com", "help": "您的 Tumblr 博客地址。"},
    },
    "hatena": {
        "hatena_id": {"label": "Hatena ID", "type": "text",
                      "placeholder": "your-hatena-id",
                      "help": "Hatena 登录用户名（即 hatenablog.com 子域前缀）。"},
        "blog_id": {"label": "博客 ID", "type": "text",
                    "placeholder": "your-hatena-id.hatenablog.com",
                    "help": "博客完整域名，在 Hatena Blog → 管理 → 详细设置中可见。"},
        "api_key": {"label": "AtomPub API Key", "type": "password",
                    "placeholder": "Hatena Blog → 详细设置 → AtomPub → API Key",
                    "help": "高敏感密钥，请勿分享。在 Hatena Blog 设置页的 AtomPub 区段取得。"},
    },
    "zenn": {
        "token": {"label": "GitHub PAT", "type": "password", "placeholder": "ghp_...",
                  "help": "GitHub → Settings → Developer settings → PAT，需 contents:write 权限。"},
        "github_repo": {"label": "GitHub 仓库", "type": "text",
                        "placeholder": "owner/zenn-articles-repo",
                        "help": "已连接 Zenn 账号的 GitHub 仓库（owner/repo 格式）。"},
        "username": {"label": "Zenn 用户名", "type": "text",
                     "placeholder": "your-zenn-username",
                     "help": "您的 Zenn 账号用户名（zenn.dev/@username 中的部分）。"},
    },
    "gitlabpages": {
        "token": {"label": "GitLab PAT", "type": "password", "placeholder": "glpat-...",
                  "help": "GitLab → Settings → Access Tokens，需 api scope（或项目级 write_repository）。"},
    },
}


def _derive(name: str) -> dict:
    """Fallback presentation for a field with no curated entry: a readable label
    from the field name, plain-text input. Keeps the form renderable even if a new
    token_fields channel lands before its labels are ported."""
    return {"label": name.replace("_", " ").title(), "type": "text", "placeholder": "", "help": ""}


def field_presentation(channel: str, auth_type: str, field_names: list[str]) -> list[dict]:
    """Build the SPA form's ``fields`` array for *channel*.

    ``field_names`` is the authoritative list from ``credential_service`` (the
    save-path single source). Each entry is enriched with presentation only; the
    ``secret`` flag (password input → never pre-filled, blank-preserves) is derived
    from the input type. No values are ever emitted — this is form metadata.
    """
    chan_map = _TOKEN_FIELDS_PRESENTATION.get(channel, {}) if auth_type == "token_fields" else {}
    fields: list[dict] = []
    for name in field_names:
        meta = chan_map.get(name) or _GENERIC_FIELDS.get(name) or _derive(name)
        fields.append({
            "name": name,
            "label": meta["label"],
            "type": meta["type"],
            "placeholder": meta.get("placeholder", ""),
            "help": meta.get("help", ""),
            "secret": meta["type"] == "password",
        })
    return fields
