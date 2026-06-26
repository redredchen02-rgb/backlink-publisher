"""GlobalSettingsAPI — global (non-channel) settings saves, transport-neutral.

Phase-A facade (Plan 2026-06-18-002 U7, Settings increment — the last Settings
backend piece). The validation + persistence of the two global settings forms was
**moved here, not copied**, from ``routes/settings_basic.py``:

  * ``save_keywords`` — the SEO anchor keyword pools (per-domain): strip / drop
    blanks, reject any keyword >60 chars, de-dup within a domain (tracking which
    domains were de-duped), then ``save_config(target_anchor_keywords=...)``.
  * ``save_schedule`` — the publish cadence: parse min-interval / jitter, clamp to
    floor (>=0.5h, >=0min), then ``settings_service.save_schedule_settings``.

Both the legacy HTML routes and the new ``/api/v1/settings/{keywords,schedule}``
JSON bindings call these and only differ in how they shape the input (form-indexed
fields vs JSON body) and render the neutral :class:`GlobalSettingsResult`. These are
global config writes (config.toml / schedule-settings.json), NOT 0600 credential
files — so, like the OAuth / diagnostics routes, they carry no inline transport
guard (covered at runtime by the app-level origin guard). This module performs no
transport concerns — it never touches ``flask.request`` and never aborts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from backlink_publisher.config import load_config, save_config

from ..helpers.contexts import _load_schedule_settings, _save_schedule_settings


@dataclass(frozen=True)
class GlobalSettingsResult:
    """Transport-neutral outcome of a global settings save.

    ``level`` drives the legacy flash type (success / danger). ``error_class`` is
    set only on failure and selects the ``/api/v1`` status: ``invalid_request`` →
    422, ``persistence_failure`` → 502.
    """

    level: str
    message: str
    error_class: str | None = None
    fragment: str = ""

    @property
    def ok(self) -> bool:
        return self.error_class is None


_MAX_KEYWORD_LEN = 60


class GlobalSettingsAPI:
    """Stateless facade; instantiate per call (mirrors the other api/*_api facades)."""

    def get_keywords(self) -> dict:
        """Read the keyword-pool editor state: the known target domains (the union
        of blog-id-mapped + already-pooled domains, what the legacy ``all_targets``
        computed) plus each domain's current pool."""
        cfg = load_config()
        targets = sorted(set(cfg.blogger_blog_ids.keys()) | set(cfg.target_anchor_keywords.keys()))
        return {"targets": targets, "pools": dict(cfg.target_anchor_keywords)}

    def get_schedule(self) -> dict:
        """Read the current publish-cadence settings."""
        s = _load_schedule_settings()
        return {
            "min_interval_hours": s.get("min_interval_hours"),
            "jitter_minutes": s.get("jitter_minutes"),
        }

    def save_keywords(self, pools: Mapping[str, list]) -> GlobalSettingsResult:
        """Validate + de-dup the per-domain anchor keyword pools, then persist.

        ``pools`` maps each target domain to its raw keyword lines (already split
        from the textarea on the form transport, a JSON list on the API transport).
        The strip / blank-drop / >60-reject / de-dup cleaning is single-sourced here.
        """
        cleaned: dict[str, list] = {}
        dup_domains: set[str] = set()
        for domain, raw in pools.items():
            domain = (domain or "").strip()
            if not domain:
                continue
            lines = [str(kw).strip() for kw in raw if str(kw).strip()]
            too_long = next((ln for ln in lines if len(ln) > _MAX_KEYWORD_LEN), None)
            if too_long is not None:
                return GlobalSettingsResult(
                    "danger", f"关键词过长（>60字符）: {too_long[:30]}…",
                    error_class="invalid_request",
                )
            seen: set[str] = set()
            deduped: list[str] = []
            for kw in lines:
                if kw in seen:
                    dup_domains.add(domain)
                else:
                    seen.add(kw)
                    deduped.append(kw)
            cleaned[domain] = deduped

        try:
            save_config(load_config(), target_anchor_keywords=cleaned, target_three_url=None)
        except Exception as e:
            return GlobalSettingsResult("danger", f"保存失败: {e}", error_class="persistence_failure")

        msg = "关键词已保存"
        if dup_domains:
            msg += f"（已自动去重 {len(dup_domains)} 个域名）"
        return GlobalSettingsResult("success", msg)

    def save_schedule(self, fields: Mapping) -> GlobalSettingsResult:
        """Parse + clamp the publish-cadence settings, then persist."""
        try:
            min_hours = float(fields.get("min_interval_hours", 4))
            jitter_mins = int(fields.get("jitter_minutes", 30))
        except (TypeError, ValueError) as e:
            return GlobalSettingsResult("danger", f"保存失败: {e}", error_class="invalid_request")
        try:
            _save_schedule_settings({
                "min_interval_hours": max(0.5, min_hours),
                "jitter_minutes": max(0, jitter_mins),
            })
        except Exception as e:
            return GlobalSettingsResult("danger", f"保存失败: {e}", error_class="persistence_failure")
        return GlobalSettingsResult("success", "排程设定已保存")
