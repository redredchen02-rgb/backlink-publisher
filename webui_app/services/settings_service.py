"""Settings and configuration helpers — Plan 2026-06-01-001 U4.

Flask-free module: all functions are testable without a request context.
contexts.py delegates data-fetching to this service; Flask coupling
(_render, _settings_context session assembly) stays in contexts.py.
"""
from __future__ import annotations

import json
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

from backlink_publisher import checkpoint as _checkpoint_mod
from backlink_publisher._util.logger import plan_logger
from backlink_publisher.config import (
    _config_dir,
    load_config,
    merge_site_url_categories,
    save_config,
    upgrade_target_to_threeurl,
)

from webui_store import (
    drafts_store as _drafts_store,
    history_store as _history_store,
    schedule_store as _schedule_store,
)


# ── LLM settings ─────────────────────────────────────────────────────────────

def llm_settings_file() -> Path:
    """Return the path to llm-settings.json (lazy, honors env rebinds)."""
    return _config_dir() / "llm-settings.json"


def load_llm_settings() -> dict:
    """Load LLM settings from disk, auto-fixing loose perms.

    Pre-#140 code shipped without a chmod, leaving llm-settings.json
    world-readable at 0o644. This loader auto-fixes on read — copied
    verbatim from contexts.py per plan (dedup would silently skip old files).
    """
    defaults = {
        "api_key": "",
        "endpoint": "",
        "model": "",
        "temperature": 0.7,
        "system_prompt": "",
        "use_article_gen": False,
        "article_system_prompt": "",
        "image_gen_api_key": "",
        "image_gen_endpoint": "",
        "image_gen_model": "",
        "image_gen_banner_size": "1200x630",
        "use_image_gen": False,
    }
    path = llm_settings_file()
    if path.exists():
        # O8: pre-#140 code hand-rolled this write and shipped without a
        # chmod, leaving llm-settings.json world-readable at 0o644. Auto-fix
        # loose perms on load (warn-don't-fail; cp-induced 0o644 is far more
        # common than tampering). Block must be verbatim — dedup would silently
        # skip old 0o644 files that the writer never re-touches (plan U4 note).
        try:
            mode = os.stat(path).st_mode & 0o777
            if mode != 0o600:
                plan_logger.warn(
                    "llm-settings.json loose perms — auto-chmod to 0o600",
                    mode=oct(mode),
                )
                os.chmod(path, 0o600)
        except OSError:
            plan_logger.warn("failed to chmod llm-settings.json to 0o600")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            defaults.update(data)
        except Exception:
            plan_logger.warn("failed to parse llm-settings.json, using defaults")
    return defaults


# ── Schedule settings ─────────────────────────────────────────────────────────

def load_schedule_settings() -> dict:
    """Load scheduling settings from the schedule store."""
    defaults = {"min_interval_hours": 4, "jitter_minutes": 30}
    loaded = _schedule_store.load()
    if isinstance(loaded, dict):
        defaults.update(loaded)
    return defaults


def save_schedule_settings(data: dict) -> None:
    """Persist scheduling settings to the schedule store."""
    _schedule_store.save(data)


# ── Schedule time calculation ─────────────────────────────────────────────────

def calc_next_available(requested_dt: datetime) -> datetime:
    """Return the earliest publish time respecting min-interval + jitter."""
    settings = load_schedule_settings()
    min_hours = settings.get("min_interval_hours", 4)
    jitter_mins = settings.get("jitter_minutes", 30)

    last_published = None
    for item in _drafts_store.load():
        if item.get("status") in ("published", "scheduled"):
            ts = item.get("published_at") or item.get("scheduled_at")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts) if "T" in ts else \
                        datetime.strptime(ts, "%Y-%m-%d %H:%M")
                    if last_published is None or dt > last_published:
                        last_published = dt
                except ValueError:
                    plan_logger.warn("calc_next_available: bad date in drafts_store", ts=ts)

    for item in _history_store.load():
        ts = item.get("created_at")
        if ts and item.get("status") in ("drafted", "published"):
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M")
                if last_published is None or dt > last_published:
                    last_published = dt
            except ValueError:
                plan_logger.warn("calc_next_available: bad date in history_store", ts=ts)

    if last_published is None:
        return requested_dt
    earliest = last_published + timedelta(hours=min_hours)
    if jitter_mins > 0:
        earliest += timedelta(minutes=random.randint(0, jitter_mins))
    return max(requested_dt, earliest)


# ── Three-tier config persistence ─────────────────────────────────────────────

def persist_three_tier_config(main_url: str, category_url: str, work_url: str) -> None:
    """Persist the homepage form's three-tier URL data via ThreeUrlConfig."""
    cfg = load_config()
    upgraded = upgrade_target_to_threeurl(
        cfg,
        main_url=main_url,
        category_url=category_url or None,
        work_url=work_url or None,
    )
    domain_key = main_url.rstrip("/")
    merged = dict(cfg.target_three_url)
    merged[domain_key] = upgraded
    save_config(cfg, target_anchor_keywords=None, target_three_url=merged)

    site_additions: dict[str, str] = {"home": main_url}
    if category_url:
        site_additions["category"] = category_url
    merge_site_url_categories(main_url, site_additions)

    plan_logger.recon(
        "homepage_form_persisted",
        main=main_url,
        list_url=upgraded.list_url,
        work_count=len(upgraded.work_urls),
    )


# ── Checkpoint ────────────────────────────────────────────────────────────────

def load_incomplete_run() -> dict | None:
    """Return the most recent incomplete checkpoint run with pending_count, or None."""
    try:
        runs = _checkpoint_mod.list_incomplete()
    except Exception:
        return None
    if not runs:
        return None
    run = runs[0]
    pending_count = sum(
        1 for i in run.get("items", []) if i.get("status") in ("pending", "failed")
    )
    return {**run, "pending_count": pending_count}


# ── Token-paste status ────────────────────────────────────────────────────────

def token_paste_status(cfg, channel: str, load_fn, *, token_field: str = "token") -> dict:
    """Status dict for a single-token channel card.

    Reads the platform's token file via ``load_fn``. Returns
    {bound, masked, dofollow}. Defensive against any load failure.
    """
    from backlink_publisher.publishing.registry import dofollow_status  # lazy
    try:
        token_path_attr = f"{channel}_token_path"
        token_path = getattr(cfg, token_path_attr, None)
        data = load_fn(token_path) if token_path else load_fn()
    except Exception:
        data = None
    token = (data or {}).get(token_field, "") if isinstance(data, dict) else ""
    bound = bool(token)
    if bound and len(token) > 6:
        masked = token[:3] + "*" * (len(token) - 6) + token[-3:]
    elif bound:
        masked = "*" * len(token)
    else:
        masked = ""
    return {
        "bound": bound,
        "masked": masked,
        "dofollow": dofollow_status(channel),
    }


def token_paste_status_notion(cfg, load_fn) -> dict:
    """Status dict for the Notion token-paste card (two-field variant)."""
    from backlink_publisher.publishing.registry import dofollow_status  # lazy
    try:
        token_path = getattr(cfg, "notion_token_path", None)
        data = load_fn(token_path) if token_path else load_fn()
    except Exception:
        data = None
    integration_token = (data or {}).get("integration_token", "") if isinstance(data, dict) else ""
    database_id = (data or {}).get("database_id", "") if isinstance(data, dict) else ""
    bound = bool(integration_token and database_id)
    if bound and len(integration_token) > 6:
        masked = integration_token[:3] + "*" * (len(integration_token) - 6) + integration_token[-3:]
    elif bound:
        masked = "*" * len(integration_token)
    else:
        masked = ""
    return {
        "bound": bound,
        "masked": masked,
        "dofollow": dofollow_status("notion"),
        "database_id_set": bool(database_id),
    }


# ── History grouping ──────────────────────────────────────────────────────────

def group_history(items: list[dict]) -> list[dict]:
    """Group consecutive history items by run_id into collapsible run-groups.

    Items sharing a run_id fold into one group; items without run_id each
    form a group of size 1. Each group has: run_id, rows, created_at,
    platform, language, n_published, n_drafted, n_failed, n_unverified,
    n_total, is_multi.
    """
    groups: list[dict] = []
    current: dict | None = None
    for item in items:
        rid = item.get("run_id")
        if rid and current and current["run_id"] == rid:
            current["rows"].append(item)
        else:
            current = {
                "run_id": rid,
                "rows": [item],
                "created_at": item.get("created_at", ""),
                "platform": item.get("platform", ""),
                "language": item.get("language", ""),
            }
            groups.append(current)
    for g in groups:
        statuses = [i.get("status", "") for i in g["rows"]]
        g["n_published"] = sum(1 for s in statuses if s in ("published", "success"))
        g["n_drafted"] = sum(1 for s in statuses if s == "drafted")
        g["n_failed"] = sum(1 for s in statuses if s == "failed")
        g["n_unverified"] = sum(1 for s in statuses if "unverified" in s)
        g["n_total"] = len(g["rows"])
        g["is_multi"] = g["n_total"] > 1
    return groups
