"""BloggerSettingsAPI — Blogger blog-ID mapping (publish routing), transport-neutral.

Phase-A facade (Plan 2026-06-18-002 U7, Settings section 3 slice 6). The blog-ID
mapping save — strip / drop-empty / dedup-by-domain plus the config write — was
**moved here, not copied**, from the legacy ``/settings/save-blog-ids`` route; the
read delegates to ``cfg.blogger_blog_ids``. Both the legacy route and the new
``/api/v1/settings/blogger/blog-ids`` bindings call this facade, so the cleaning
rule is single-sourced and cannot drift between transports.

This is the domain → Blogger Blog ID routing map consulted at publish time (NOT an
OAuth credential), so it gets its own facade rather than living on OAuthAPI.
``load_config`` / ``save_config`` are module-top imports so tests patch them here.
Flask-free: no request access, never aborts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from backlink_publisher.config import load_config, save_config


@dataclass(frozen=True)
class BlogIdsResult:
    """Transport-neutral outcome of a blog-ID mapping save. ``error_class`` selects
    the ``/api/v1`` status (``persistence_failure`` → 502); the legacy route reads
    ``level`` for the flash type and ``fragment`` for the redirect anchor."""

    level: str
    message: str
    error_class: str | None = None
    fragment: str = "channel-blogger"

    @property
    def ok(self) -> bool:
        return self.error_class is None


class BloggerSettingsAPI:
    """Stateless facade; instantiate per call (mirrors the other api/*_api facades)."""

    def get_blog_ids(self) -> dict[str, str]:
        """The current domain → Blogger Blog ID mapping."""
        return dict(load_config().blogger_blog_ids)

    def save_blog_ids(self, mapping: Mapping[str, str]) -> BlogIdsResult:
        """Persist the mapping. Each entry is stripped; blank domain/id pairs are
        dropped; a later row wins on a duplicate domain (the single-source cleaning
        rule moved out of the legacy route)."""
        cleaned: dict[str, str] = {}
        for domain, blog_id in mapping.items():
            d, b = str(domain).strip(), str(blog_id).strip()
            if d and b:
                cleaned[d] = b
        try:
            cfg = load_config()
            cfg.blogger_blog_ids = cleaned
            save_config(cfg, extra_blogger_ids={}, target_three_url=None)
            return BlogIdsResult("success", "Blog ID 映射已保存")
        except Exception as e:
            return BlogIdsResult("danger", f"保存失败: {e}", error_class="persistence_failure")
