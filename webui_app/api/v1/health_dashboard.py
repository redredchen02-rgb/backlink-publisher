"""Health dashboard API for ``/api/v1`` -- Plan 2026-07-02-001 U6.

JSON sibling of the legacy ``/ce:health`` Jinja page plus its
``/ce:health/pause``, ``/ce:health/reverify``, ``/ce:health/circuit-reset``,
and ``/ce:health/scorecard/recheck-link`` actions. ``routes/health.py`` and
``routes/health_actions.py`` are NOT deleted (retire in U9) -- this module
calls the SAME underlying read/write functions they call, not their own
wrapper functions. ``routes/health.py``'s panel closures are genuinely
private (nested inside ``ce_health()``, not importable at all).
``health_actions.py``'s ``_config``/``_known_platform``/``_platform_arg``
ARE plain module-level functions and technically importable -- duplicated
here anyway (code review, Plan 2026-07-02-001 U6) to avoid coupling this
long-lived module to one slated for deletion in U9, not because import was
impossible.

Fail-open per panel is the real spec here: ``GET /health/summary`` always
returns 200; each panel carries its own ``degraded`` flag and a safe
empty-shape fallback, so one bad data source never drags down the rest of the
dashboard -- mirrors the existing Jinja page's per-panel try/except (R3's
"partial failure isolated" red line).

Data exposure: degraded reason strings never leak ``str(exc)`` -- only
``type(exc).__name__`` or a curated reason-code, mirroring ``_canary_rows``'s
own "no credentials/URLs" convention in ``routes/health.py``. The ONE curated
exception is reverify's ``DependencyError`` message (matches
``health_actions.py``'s existing precedent).

Security: ``api_v1`` is a single shared blueprint, so this module cannot rely
on ``health_actions.py``'s blueprint-scoped ``_enforce_loopback``
``before_request`` (that hook would also lock out ``/api/v1/health``
liveness). Each mutating/loopback-only view calls its own loopback guard
inline, mirroring ``bind.py``'s ``_enforce_loopback_addr`` precedent. CSRF and
the 60/min rate limiter are already app-level and apply to every
``/api/v1/*`` route automatically -- not re-implemented here. The
recheck-link action additionally enforces the Origin/Referer bind-origin
check inline (outbound probe -- mirrors the legacy route) and the anti-SSRF
membership gate (``_published_candidate``): the client's ``live_url`` is a
lookup key only, never the probe target.
"""

from __future__ import annotations

from collections.abc import Callable
import dataclasses
from datetime import datetime, UTC
import json
import logging
from typing import Any, TYPE_CHECKING

from flask import abort, jsonify, request

from ...helpers._request_cache import _g_cache
from ...helpers.security import _check_bind_origin_or_abort, _LOOPBACK_HOSTS
from . import bp
from .errors import ApiProblem

if TYPE_CHECKING:
    from backlink_publisher.events import EventStore

_log = logging.getLogger(__name__)


def _enforce_loopback_addr() -> None:
    """Mirror ``bind.py``'s per-view loopback gate -- see module docstring for
    why this can't be a blueprint-level ``before_request`` here."""
    if request.remote_addr not in _LOOPBACK_HOSTS:
        abort(403)


def _sanitize_reason(reason: str | None) -> str | None:
    """Never let ``str(exc)`` cross this API boundary. ``events.reconcile``'s
    own ``ReadProjectionResult.degraded_reason`` is set internally as
    ``f"{type(exc).__name__}: {exc}"`` -- truncate to just the class name."""
    if reason is None:
        return None
    return reason.split(": ", 1)[0]


def _panel(cache_key: str, fn: Callable[[], Any], fallback: Any) -> dict[str, Any]:
    """Wrap one read-only health data source: cache within the request via
    ``_g_cache``, and on any failure fall back to a safe empty shape with
    ``degraded=True`` instead of letting the whole summary 500."""
    try:
        return {"data": _g_cache(cache_key, fn), "degraded": False}
    except Exception as exc:
        _log.warning("health API: %s panel failed: %s", cache_key, exc)
        return {"data": fallback, "degraded": True}


# ── panel data sources (module-level so `_panel()` can call them directly --
#    routes/health.py's equivalents are closures nested inside ce_health() and
#    not importable) ───────────────────────────────────────────────────────


def _health_agg() -> dict[str, Any]:
    """Mirrors ``ce_health()``'s ``_build()``: U1 projection backstop, then
    the U2 aggregation. Self-reports degradation via the returned dict rather
    than raising, matching the legacy closure's own design (a genuinely
    degraded-but-populated Health object beats no health data at all).

    Both ``project_on_read()`` and ``build_health()`` get their own try/except
    -- code review finding: an earlier version only wrapped ``build_health()``,
    so a ``project_on_read()`` failure would propagate out of this function
    entirely, collapsing BOTH ``health`` and ``projection`` to null at the
    ``_panel()`` layer and (per ``HealthPage.vue``'s `v-if="health && panels"`
    gate) silently blanking the whole dashboard -- worse than the legacy
    Jinja page's honest "temporarily unavailable" fallback for this one axis.
    """
    from backlink_publisher.events.reconcile import ReadProjectionResult

    from ...health_metrics import (
        _window_start,
        build_health,
        DEFAULT_WINDOW_DAYS,
        Health,
        SuccessRate,
    )
    from ...services.health_projection import project_on_read

    try:
        projection = project_on_read()
    except Exception as exc:
        _log.warning("health API: project_on_read failed: %s", exc)
        projection = ReadProjectionResult(degraded=True, degraded_reason=type(exc).__name__)

    try:
        health = build_health()
    except Exception as exc:
        _log.warning("health API: build_health failed: %s", exc)
        health = Health(
            window_days=DEFAULT_WINDOW_DAYS,
            since_utc=_window_start(datetime.now(UTC), DEFAULT_WINDOW_DAYS),
            success=SuccessRate(),
        )
        projection = dataclasses.replace(
            projection,
            degraded=True,
            degraded_reason=projection.degraded_reason or type(exc).__name__,
        )
    proj_dict = dataclasses.asdict(projection)
    proj_dict["degraded_reason"] = _sanitize_reason(proj_dict.get("degraded_reason"))
    return {"projection": proj_dict, "health": dataclasses.asdict(health)}


def _canary_rows() -> list[dict]:
    from backlink_publisher.canary.store import list_all

    rows = []
    for platform, rec in sorted((list_all() or {}).items()):
        rows.append({
            "platform": platform,
            "status": rec.get("status"),
            "consecutive_failures": rec.get("consecutive_failures", 0),
            "consecutive_oks": rec.get("consecutive_oks", 0),
            "quarantined": bool(rec.get("quarantined", False)),
            "last_ok_at": rec.get("last_ok_at"),
            "last_drift_at": rec.get("last_drift_at"),
        })
    return rows


def _forward_path_rows() -> list[dict]:
    from backlink_publisher.canary.store import list_publish_path_all

    rows = []
    for platform, rec in sorted((list_publish_path_all() or {}).items()):
        rows.append({
            "platform": platform,
            "status": rec.get("status"),
            "consecutive_failures": rec.get("consecutive_failures", 0),
            "consecutive_oks": rec.get("consecutive_oks", 0),
            "degraded": bool(rec.get("degraded", False)),
            "last_ok_at": rec.get("last_ok_at"),
            "last_drift_at": rec.get("last_drift_at"),
        })
    return rows


def _reconciliation_gaps() -> dict[str, int]:
    from backlink_publisher.checkpoint import list_failed_items
    from backlink_publisher.events import EventStore

    pending = len(list_failed_items())
    rows = EventStore().query(
        "SELECT COUNT(*) FROM quarantine_log "
        "WHERE json_extract(raw_payload_json, '$.failure_type') = ?",
        ("reconcile_gap",),
    )
    gaps = int(rows[0][0]) if rows else 0
    return {"pending_checkpoints": pending, "quarantine_gaps": gaps}


def _decay_counts() -> dict[str, int]:
    from ...health_metrics import decay_counts

    return decay_counts()


def _scorecard_rows() -> list[dict]:
    from backlink_publisher.scorecard import build_channel_scorecard

    return [r.to_jsonl_dict() for r in build_channel_scorecard()]


def _geo_panel() -> dict[str, Any]:
    from backlink_publisher.events import EventStore

    from ...health_metrics import geo_citation_share

    rows = geo_citation_share(EventStore())
    return {"targets": rows} if rows else {}


def _pipeline_summary() -> dict[str, Any]:
    import time

    from backlink_publisher.config.loader import _config_dir
    from backlink_publisher.events import EventStore

    db_path = _config_dir() / "events.db"
    if not db_path.exists():
        return {}

    store = EventStore()
    now = time.time()
    windows = {"w24h": now - 86400, "w7d": now - 604800, "w30d": now - 2592000}

    result: dict[str, Any] = {}
    for wname, since_ts in windows.items():
        rows = store.query(
            "SELECT json_extract(payload_json, '$.status') as status, COUNT(*) as cnt "
            "FROM events WHERE kind IN ('publish.confirmed','publish.unverified','publish.failed') "
            "AND ts_utc >= ? GROUP BY status",
            (since_ts,),
        )
        row_map: dict[str, int] = {}
        for r in rows:
            row_map[r["status"] or "unknown"] = r["cnt"]
        result[wname] = {
            "ok": row_map.get("published", 0) + row_map.get("ok", 0),
            "fail": sum(v for k, v in row_map.items() if k not in ("published", "ok")),
        }

    rows = store.query("SELECT MAX(ts_utc) as max_ts FROM events WHERE kind='link.rechecked'")
    last_ts = rows[0]["max_ts"] if rows and rows[0]["max_ts"] else None
    if last_ts:
        import datetime as _dt

        result["last_recheck"] = _dt.datetime.fromtimestamp(last_ts, tz=_dt.UTC).isoformat()
    else:
        result["last_recheck"] = None
    return result


_EVENTS_DB_WARN_MB = 100.0
_EVENTS_WARN_ROWS = 100_000


def _storage_health() -> dict[str, Any]:
    import os
    import sqlite3

    from backlink_publisher.config.loader import _config_dir

    cfg = _config_dir()

    def _mb(path: Any) -> float:
        try:
            return round(os.path.getsize(path) / 1_048_576, 2)
        except OSError:
            return 0.0

    def _dir_mb(dirpath: Any) -> float:
        try:
            total = 0
            for root, _, files in os.walk(dirpath):
                for fname in files:
                    try:
                        total += os.path.getsize(os.path.join(root, fname))
                    except OSError:
                        pass
            return round(total / 1_048_576, 2)
        except OSError:
            return 0.0

    events_db_mb = _mb(cfg / "events.db")
    events_rows = 0
    articles_rows = 0
    try:
        db_path = cfg / "events.db"
        if db_path.exists():
            with sqlite3.connect(str(db_path), timeout=2.0) as con:
                events_rows = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                articles_rows = con.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    except Exception as exc:
        _log.debug("health API: events.db row count failed: %s", exc)

    return {
        "events_db_mb": events_db_mb,
        "dedup_db_mb": _mb(cfg / "dedup.db"),
        "config_dir_mb": _dir_mb(cfg),
        "events_rows": events_rows,
        "articles_rows": articles_rows,
        "events_db_warn": events_db_mb > _EVENTS_DB_WARN_MB or events_rows > _EVENTS_WARN_ROWS,
    }


def _platform_health() -> dict[str, Any]:
    from backlink_publisher.config import load_config
    from backlink_publisher.health.aggregate import build_platform_health

    cfg = _g_cache("health_api_config", load_config)
    return build_platform_health(cfg)


def _autopilot_alerts() -> list[dict]:
    import webui_store as _ws

    targets = _ws.schedule_store.load().get("autopilot_targets", {})
    return [
        {"site_url": url, **cfg} for url, cfg in targets.items() if cfg.get("alert_pending")
    ]


def _weights_snapshot() -> dict | None:
    from ...health_metrics import weights_snapshot

    return weights_snapshot()


def _decay_alerts() -> list[dict]:
    from datetime import timedelta

    from backlink_publisher.events import EventStore
    from backlink_publisher.events.kinds import DECAY_ALERT

    store = EventStore()
    since = (datetime.now(UTC) - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = store.query(
        """
        SELECT target_url, ts_utc,
               json_extract(payload_json, '$.lost_count') AS lost_count
        FROM events
        WHERE kind = ? AND ts_utc >= ? AND target_url IS NOT NULL
        ORDER BY ts_utc DESC
        """,
        (DECAY_ALERT, since),
    )
    return [
        {"target_url": r["target_url"], "lost_count": r["lost_count"], "ts": r["ts_utc"]}
        for r in rows
    ]


def _gsc_indexation_panel() -> list[dict]:
    from backlink_publisher.events import EventStore

    from ...health_metrics import indexation_status

    return indexation_status(EventStore())


def _gsc_ranking_panel() -> list[dict]:
    from backlink_publisher.events import EventStore

    from ...health_metrics import ranking_trend

    return ranking_trend(EventStore())


def _publish_index_latency() -> list[dict]:
    from backlink_publisher.events import EventStore

    from ...health_metrics import publish_to_index_latency

    return publish_to_index_latency(EventStore())


def _index_rate_by_channel() -> list[dict]:
    from backlink_publisher.events import EventStore

    from ...health_metrics import index_rate_by_channel

    return index_rate_by_channel(EventStore())


def _impression_analysis() -> list[dict]:
    from backlink_publisher.events import EventStore

    from ...health_metrics import impression_analysis

    return impression_analysis(EventStore())


def _ranking_lift_analysis() -> list[dict]:
    from backlink_publisher.events import EventStore

    from ...health_metrics import ranking_lift_analysis

    return ranking_lift_analysis(EventStore())


def _referral_conversion() -> list[dict]:
    from backlink_publisher.events import EventStore

    from ...health_metrics import referral_conversion

    return referral_conversion(EventStore())


def _cost_metrics() -> dict[str, Any]:
    from backlink_publisher.events import EventStore

    from ...health_metrics import cost_metrics

    return cost_metrics(EventStore())


def _decisions_by_platform() -> list[dict]:
    from backlink_publisher.events import EventStore

    from ...health_metrics import decisions_by_platform

    return decisions_by_platform(EventStore())


def _publish_metrics() -> dict[str, Any]:
    from dataclasses import asdict

    from backlink_publisher.publishing.reliability.policy import enforce_allowlist, policy_mode
    from backlink_publisher.scorecard.coverage import recheck_coverage
    from backlink_publisher.scorecard.reliability_readiness import channel_readiness
    from backlink_publisher.scorecard.success_rate import publish_success_rate

    success = _g_cache("health_api_publish_success_rate", publish_success_rate)
    coverage = _g_cache("health_api_recheck_coverage", recheck_coverage)
    readiness = _g_cache("health_api_reliability_readiness", channel_readiness)
    return {
        "success_rate": asdict(success),
        "coverage": asdict(coverage),
        "readiness": asdict(readiness),
        "policy_mode": policy_mode(),
        "enforce_channels": sorted(enforce_allowlist()),
    }


@bp.get("/health/summary")
def health_summary() -> Any:
    """Full health-dashboard aggregate -- fail-open per panel (see module docstring)."""
    agg = _panel("health_api_agg", _health_agg, {
        "projection": None,
        "health": None,
    })
    panels = {
        "canary": _panel("health_api_canary", _canary_rows, []),
        "forward_path": _panel("health_api_forward_path", _forward_path_rows, []),
        "reconciliation_gaps": _panel("health_api_recon_gaps", _reconciliation_gaps, {}),
        "recheck_decay": _panel("health_api_decay_counts", _decay_counts, {}),
        "channel_scorecard": _panel("health_api_scorecard", _scorecard_rows, []),
        "geo_panel": _panel("health_api_geo", _geo_panel, {}),
        "pipeline_summary": _panel("health_api_pipeline_summary", _pipeline_summary, {}),
        "storage_health": _panel("health_api_storage", _storage_health, {}),
        "platform_health": _panel("health_api_platform_health", _platform_health, {}),
        "autopilot_alerts": _panel("health_api_autopilot_alerts", _autopilot_alerts, []),
        "weights_snapshot": _panel("health_api_weights", _weights_snapshot, None),
        "decay_alerts": _panel("health_api_decay_alerts", _decay_alerts, []),
        "gsc_indexation": _panel("health_api_gsc_indexation", _gsc_indexation_panel, []),
        "gsc_ranking": _panel("health_api_gsc_ranking", _gsc_ranking_panel, []),
        "publish_index_latency": _panel("health_api_idx_latency", _publish_index_latency, []),
        "index_rate_by_channel": _panel("health_api_idx_rate", _index_rate_by_channel, []),
        "impression_analysis": _panel("health_api_imp_analysis", _impression_analysis, []),
        "ranking_lift_analysis": _panel("health_api_rank_lift", _ranking_lift_analysis, []),
        "referral_conversion": _panel("health_api_ref_conv", _referral_conversion, []),
        "cost_metrics": _panel("health_api_cost_m", _cost_metrics, {}),
        "decisions_by_platform": _panel("health_api_decisions", _decisions_by_platform, []),
        "publish_metrics": _panel("health_api_publish_metrics", _publish_metrics, {
            "success_rate": None, "coverage": None, "readiness": None,
            "policy_mode": None, "enforce_channels": [],
        }),
    }
    return jsonify({
        "projection": agg["data"]["projection"],
        "health": agg["data"]["health"],
        "agg_degraded": agg["degraded"],
        "panels": panels,
    })


@bp.get("/health/scorecard/<channel>/links")
def health_scorecard_links(channel: str) -> Any:
    """Per-link drawer data for one channel (fetch-on-expand)."""
    def _links() -> Any:
        from backlink_publisher.scorecard.links import derive_links_by_channel

        return derive_links_by_channel()

    try:
        by_channel = _g_cache("health_api_scorecard_links", _links)
        rows = by_channel.get(channel, [])
        return jsonify({"ok": True, "links": [r.to_dict() for r in rows]})
    except Exception as exc:
        _log.warning("health API: scorecard links read failed for %s: %s", channel, exc)
        return jsonify({"ok": False, "links": []})


def _published_candidate(store: EventStore, live_url: str) -> dict[str, Any] | None:
    """``live_url`` -> an already-published recheck candidate, or ``None``.

    Anti-SSRF membership gate, mirroring ``routes/health.py``'s
    ``_published_candidate``: only links that already carry a
    ``publish.confirmed``/``publish.unverified`` event are probeable, and the
    probe target is the STORED event row's ``live_url``, never the client
    string (the client's ``live_url`` is a lookup key only).
    """
    from backlink_publisher._util.url import canonicalize_url
    from backlink_publisher.events import kinds

    try:
        target = canonicalize_url(live_url)
    except ValueError:
        return None
    kinds_t = (kinds.PUBLISH_CONFIRMED, kinds.PUBLISH_UNVERIFIED)
    placeholders = ",".join("?" for _ in kinds_t)
    rows = store.query(
        "SELECT article_id, target_url, host, payload_json FROM events "
        f"WHERE kind IN ({placeholders}) "
        "AND json_extract(payload_json, '$.live_url') IS NOT NULL",
        kinds_t,
    )
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (ValueError, TypeError):
            continue
        raw = payload.get("live_url")
        if not isinstance(raw, str):
            continue
        try:
            if canonicalize_url(raw) != target:
                continue
        except ValueError:
            continue
        return {
            "live_url": raw,
            "target_url": row["target_url"],
            "host": row["host"],
            "article_id": row["article_id"],
            "platform": payload.get("platform"),
        }
    return None


@bp.post("/health/scorecard/recheck-link")
def health_scorecard_recheck_link() -> Any:
    """Re-probe ONE already-published link, writing a ``link.rechecked`` event.

    Outbound probe -- enforces the bind-origin guard (DNS-rebinding /
    malicious-localhost defense) inline, on top of the app-level CSRF guard,
    matching the legacy route's own perimeter. Anti-SSRF: an unpublished
    ``live_url`` is rejected with no probe fired.
    """
    _check_bind_origin_or_abort()
    data = request.get_json(silent=True) or {}
    live_url = (data.get("live_url") or "").strip()
    if not live_url:
        raise ApiProblem(400, "live_url required", error_class="live_url_required")

    from backlink_publisher.events import EventStore

    store = EventStore()
    record = _published_candidate(store, live_url)
    if record is None:
        raise ApiProblem(404, "Not published", error_class="not_published")

    try:
        from backlink_publisher.recheck import events_io
        from backlink_publisher.recheck.probe import recheck_link

        result = recheck_link(record, probe=True, timeout=5.0)
        events_io.emit_recheck(store, [result])
    except Exception as exc:
        _log.warning("health API: scorecard recheck-link failed for %s: %s", live_url, exc)
        return jsonify({"ok": False, "error_code": "probe_failed"}), 200

    return jsonify({
        "ok": True,
        "verdict": result.get("verdict"),
        "live_url": record["live_url"],
        "last_recheck_ts": datetime.now(UTC).isoformat(timespec="seconds"),
    })


# ── maintenance actions (pause/reverify/circuit-reset) ──────────────────────
# Loopback-only, mirroring health_actions.py's blueprint-scoped guard (see
# _enforce_loopback_addr above for why it's inline here instead). CSRF and
# the app-level Origin/Referer bind-origin guard (_global_origin_guard, see
# webui_app/__init__.py) are already enforced for every /api/v1/* mutating
# route automatically -- not re-implemented inline here, matching
# health_actions.py's own original perimeter (only recheck-link is an
# outbound probe that additionally needs the inline bind-origin call). Every
# action validates the platform against the live registry first -- an
# unknown platform is a 400 with no side effect, matching the legacy actions
# exactly.


def _config() -> Any:
    from backlink_publisher.config import load_config

    return load_config()


def _known_platform(platform: str) -> bool:
    if not platform:
        return False
    try:
        from backlink_publisher.publishing.registry import registered_platforms

        return platform in registered_platforms()
    except Exception as exc:
        _log.debug("health API: registered_platforms lookup failed: %s", exc)
        return False


def _platform_arg() -> str:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("platform", "")).strip()


@bp.post("/health/actions/pause")
def health_action_pause() -> Any:
    _enforce_loopback_addr()
    platform = _platform_arg()
    if not _known_platform(platform):
        raise ApiProblem(400, "Unknown platform", error_class="unknown_platform")

    payload = request.get_json(silent=True) or {}
    paused = bool(payload.get("paused", True))
    try:
        from backlink_publisher.health.persistence import locked_store

        new_state = locked_store.set_paused(platform, paused, _config())
    except Exception as exc:
        _log.warning("health API: pause write failed for %s: %s", platform, exc)
        return jsonify({"ok": False, "platform": platform, "reason": "write_failed"}), 200
    return jsonify({"ok": True, "platform": platform, "paused": new_state})


@bp.post("/health/actions/reverify")
def health_action_reverify() -> Any:
    _enforce_loopback_addr()
    platform = _platform_arg()
    if not _known_platform(platform):
        raise ApiProblem(400, "Unknown platform", error_class="unknown_platform")

    from backlink_publisher._util.errors import DependencyError
    from backlink_publisher.publishing.adapters import verify_adapter_setup

    try:
        verify_adapter_setup(platform, _config())  # offline mode -- never a live network probe
        return jsonify({"ok": True, "platform": platform, "ready": True, "reason": ""})
    except DependencyError as exc:
        # Curated whitelist exception (matches health_actions.py's existing
        # precedent) -- this message is operator-facing setup guidance, not a
        # raw internal exception.
        return jsonify({"ok": True, "platform": platform, "ready": False, "reason": str(exc)})
    except Exception as exc:
        _log.warning("health API: reverify failed for %s: %s", platform, exc)
        return jsonify({
            "ok": False, "platform": platform, "ready": False,
            "reason": type(exc).__name__,
        }), 200


@bp.post("/health/actions/circuit-reset")
def health_action_circuit_reset() -> Any:
    _enforce_loopback_addr()
    platform = _platform_arg()
    if not _known_platform(platform):
        raise ApiProblem(400, "Unknown platform", error_class="unknown_platform")

    try:
        from backlink_publisher.publishing.reliability import circuit

        circuit.reset_circuit(platform, _config())
    except Exception as exc:
        _log.warning("health API: circuit reset failed for %s: %s", platform, exc)
        return jsonify({"ok": False, "platform": platform, "reason": "reset_failed"}), 200
    return jsonify({"ok": True, "platform": platform})
