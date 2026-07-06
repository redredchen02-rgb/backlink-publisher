"""Velog GraphQL adapter constants and configuration."""

from datetime import datetime, UTC

# ── Endpoint & Headers ────────────────────────────────────────────────────────

_VELOG_GRAPHQL_ENDPOINT = "https://v2.velog.io/graphql"

# Required headers to avoid silent-drop (P0-1 spike)
_VELOG_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)
_VELOG_REQUIRED_HEADERS = {
    "accept": "*/*",
    "content-type": "application/json",
    "origin": "https://velog.io",
    "referer": "https://velog.io/",
    "sec-fetch-site": "same-site",
    "sec-fetch-mode": "cors",
    "sec-fetch-dest": "empty",
    "user-agent": _VELOG_UA,
}

# GraphQL mutation (7-field minimal set, P0-1 confirmed)
WRITE_POST_MUTATION = (
    "mutation WritePost("
    "$title: String, $body: String, $tags: [String], "
    "$is_markdown: Boolean, $is_temp: Boolean, $is_private: Boolean, "
    "$url_slug: String, $thumbnail: String, $meta: JSON, "
    "$series_id: ID, $token: String"
    ") { writePost("
    "title: $title, body: $body, tags: $tags, "
    "is_markdown: $is_markdown, is_temp: $is_temp, is_private: $is_private, "
    "url_slug: $url_slug, thumbnail: $thumbnail, meta: $meta, "
    "series_id: $series_id, token: $token"
    ") { id user { id username __typename } url_slug __typename } }"
)

# ── Rate limiting (R18) ───────────────────────────────────────────────────────

# Phase 1 graduated rollout — change via PR, diff = audit trail
_VELOG_DAILY_CAP_INITIAL: int = 5
_VELOG_DAILY_CAP_PROD: int = 30

# Set to (Unit 4 merge date + 14 days). PR changing this value = unlock event.
UNLOCK_DATE_UTC: datetime = datetime(2026, 6, 2, 0, 0, tzinfo=UTC)

# Jitter window between posts (P0-5b)
_VELOG_JITTER_MIN_S: int = 60
_VELOG_JITTER_MAX_S: int = 180

def _velog_jitter_min_s() -> int:
    try:
        return int(__import__("os").environ.get("VELOG_THROTTLE_MIN_S", _VELOG_JITTER_MIN_S))
    except (ValueError, TypeError):
        return _VELOG_JITTER_MIN_S

def _velog_jitter_max_s() -> int:
    try:
        return int(__import__("os").environ.get("VELOG_THROTTLE_MAX_S", _VELOG_JITTER_MAX_S))
    except (ValueError, TypeError):
        return _VELOG_JITTER_MAX_S

# Request timeouts
_TIMEOUT: int = 30  # seconds per HTTP request
_PROBE_TIMEOUT: int = 10  # lightweight liveness check
_LOCK_POLL_INTERVAL: float = 0.5  # seconds
_LOCK_TIMEOUT: float = 60.0  # seconds

# Fields to mask in debug artifacts (never log token values)
_TOKEN_FIELDS = frozenset({"access_token", "refresh_token", "token"})

# Velog liveness probe — currentUser is the most common GraphQL field name.
_PROBE_QUERY = "{ currentUser { id username } }"
