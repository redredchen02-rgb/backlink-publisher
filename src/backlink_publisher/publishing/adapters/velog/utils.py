"""Velog adapter utility functions."""

from __future__ import annotations

from datetime import datetime, UTC
import json
import os
from pathlib import Path
import re
from typing import Any

from backlink_publisher.config import Config

from .constants import (
    _TOKEN_FIELDS,
    _VELOG_DAILY_CAP_INITIAL,
    _VELOG_DAILY_CAP_PROD,
    UNLOCK_DATE_UTC,
)

# ── Helper functions ──────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Convert *text* to a URL-safe slug (lowercase, hyphens, ASCII-ish)."""
    slug = text.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)  # remove punctuation except - and _
    slug = re.sub(r"[\s_]+", "-", slug)   # spaces → hyphens
    slug = re.sub(r"-+", "-", slug)        # collapse repeated hyphens
    slug = slug.strip("-")
    return slug or "post"


def _json_log(**kwargs: Any) -> str:
    return json.dumps(kwargs)


def _mask_cookies(cookies: dict[str, str]) -> dict[str, str]:
    """Return a copy of *cookies* with token values replaced by '<masked>'."""
    return {k: ("<masked>" if k in _TOKEN_FIELDS else v) for k, v in cookies.items()}


def _save_null_artifact(
    resp_json: dict[str, Any],
    resp_headers: dict[str, str],
    article_id: str,
    config: Config,
) -> str | None:
    """Persist the full null-after-retry response to a debug artifact file.

    Writes ``<config_dir>/debug/velog-null-<article_id>.json`` (0600).
    Returns the artifact path on success, ``None`` if the write fails.
    Never raises — I/O errors are swallowed so a debug write cannot break
    the publish path.
    """
    try:
        debug_dir = config.config_dir / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = debug_dir / f"velog-null-{article_id}.json"
        payload = {
            "adapter": "velog-graphql",
            "article_id": article_id,
            "response_body": resp_json,
            "response_headers": dict(resp_headers),
            "gql_errors": resp_json.get("errors") or [],
        }
        old_umask = os.umask(0o077)
        try:
            tmp = artifact_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, artifact_path)
            os.chmod(artifact_path, 0o600)
        finally:
            os.umask(old_umask)
        return str(artifact_path)
    except (OSError, TypeError):
        return None


def _effective_cap() -> int:
    now = datetime.now(UTC)
    if now >= UNLOCK_DATE_UTC:
        return _VELOG_DAILY_CAP_PROD
    return _VELOG_DAILY_CAP_INITIAL


def _utc_today_iso() -> str:
    """Return today's date in UTC as ISO-8601 — the canonical reset boundary."""
    return datetime.now(UTC).date().isoformat()


def _read_count(count_path: Path) -> tuple[int, float]:
    """Read ``(count, last_publish_at)`` from *count_path*, resetting on new UTC day."""
    today = _utc_today_iso()
    try:
        data = json.loads(count_path.read_text(encoding="utf-8"))
        if data.get("date_utc") != today:
            return 0, 0.0
        return int(data.get("count", 0)), float(data.get("last_publish_at", 0.0))
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return 0, 0.0


def _write_count(count_path: Path, count: int, last_publish_at: float) -> None:
    today = _utc_today_iso()
    payload = {"date_utc": today, "count": count, "last_publish_at": last_publish_at}
    tmp = count_path.with_suffix(".tmp")
    old_umask = os.umask(0o077)
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, count_path)
        os.chmod(count_path, 0o600)
    finally:
        os.umask(old_umask)
