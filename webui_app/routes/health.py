"""/ce:health — publishing health dashboard (read-only).

Plan 2026-05-25-006 / U3. On load, runs the single-flight project-on-read
backstop (U1) so WebUI-sourced and crash-stranded outcomes are reflected, then
the read-only aggregations (U2), and renders them with honest empty / freshness
/ gap states. GET-only → the CSRF guard (mutating verbs only) does not apply.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, request

from ..helpers.contexts import _render
from ..helpers._request_cache import _g_cache
from ..helpers.security import _check_bind_origin_or_abort
from ..services.alerting import alert_registry

if TYPE_CHECKING:
    from backlink_publisher.events.store import EventStore

bp = Blueprint("health", __name__)

_log = logging.getLogger(__name__)


@bp.route("/ce:health/scorecard/<channel>/links", methods=["GET"])
def ce_health_scorecard_links(channel: str):
    """Per-link drawer data for one channel (Plan 2026-06-05-009 U2).

    GET-only, read-only. Returns the latest ``link.rechecked`` verdict of every
    published link under ``channel`` (fetch-on-expand under the scorecard card).
    Fail-open with an explicit ``ok`` flag so the client distinguishes a
    legitimately-empty channel (``{ok:true, links:[]}``) from a backend error
    (``{ok:false, links:[]}``). ``derive_links_by_channel`` is called once
    (returns all channels) and indexed here, per the U1 perf advisory.
    """
    def _links():
        from backlink_publisher.scorecard.links import derive_links_by_channel
        return derive_links_by_channel()

    try:
        by_channel = _g_cache("scorecard_links", _links)
        rows = by_channel.get(channel, [])
        return jsonify({"ok": True, "links": [r.to_dict() for r in rows]})
    except Exception as exc:  # noqa: BLE001 — read-only GET must never 500
        _log.warning("health: scorecard links read failed for %s: %s", channel, exc)
        return jsonify({"ok": False, "links": []})


@bp.route("/ce:health/publish-metrics", methods=["GET"])
def ce_health_publish_metrics():
    """Publish success-rate (B2) + recheck coverage (B1) as JSON.

    GET-only, read-only. Surfaces the per-channel publish success % (distinct
    from liveness ``live_pct``) and the within-window recheck coverage against
    the >=50% target (Plan 2026-06-15-001). Fail-open with an ``ok`` flag so the
    client distinguishes empty data from a backend error.
    """
    from dataclasses import asdict

    try:
        from backlink_publisher.scorecard.coverage import recheck_coverage
        from backlink_publisher.scorecard.success_rate import publish_success_rate
        from backlink_publisher.scorecard.reliability_readiness import channel_readiness
        from backlink_publisher.publishing.reliability.policy import (
            enforce_allowlist,
            policy_mode,
        )

        success = _g_cache("publish_success_rate", lambda: publish_success_rate())
        coverage = _g_cache("recheck_coverage", lambda: recheck_coverage())
        readiness = _g_cache("reliability_readiness", lambda: channel_readiness())
        # Per-channel enforce mode = policy_mode when the channel is in
        # enforce_channels, else observe behavior (Unit 7). The panel derives the
        # per-channel mode from policy_mode + enforce_channels.
        return jsonify(
            {
                "ok": True,
                "success_rate": asdict(success),
                "coverage": asdict(coverage),
                "readiness": asdict(readiness),
                "policy_mode": policy_mode(),
                "enforce_channels": sorted(enforce_allowlist()),
            }
        )
    except Exception as exc:  # noqa: BLE001 — read-only GET must never 500
        _log.warning("health: publish-metrics read failed: %s", exc)
        return jsonify(
            {
                "ok": False,
                "success_rate": None,
                "coverage": None,
                "readiness": None,
                "policy_mode": None,
                "enforce_channels": [],
            }
        )


def _published_candidate(store: "EventStore", live_url: str) -> dict[str, Any] | None:
    """``live_url`` → an already-published recheck candidate, or ``None`` (R8).

    Anti-SSRF membership gate: only links that already carry a
    ``publish.confirmed`` / ``publish.unverified`` event are probeable. The
    candidate's URLs come from the STORED event row, never the client string —
    the client supplies ``live_url`` only as a lookup key. Mirrors the
    ``equity_ledger_recheck`` precedent (client value is a key, not a probe target).
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
        f"WHERE kind IN ({placeholders})",
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


@bp.route("/ce:health/scorecard/recheck-link", methods=["POST"])
def ce_health_scorecard_recheck_link():
    """Re-probe ONE already-published link, writing a ``link.rechecked`` event
    (Plan 2026-06-05-009 U4).

    Outbound probe → the Origin guard (DNS-rebinding / malicious-localhost defense)
    is enforced on top of the app-level CSRF guard (mirror ``keep_alive``). R8
    anti-SSRF: the client ``live_url`` is a lookup key only; an unpublished URL is
    rejected with NO probe fired. Goes through the keepalive ``emit_recheck`` path
    (the sole ``link.rechecked`` writer) — NOT the binary ``recheck_one``. Honest
    structured result: a PROBE_ERROR *verdict* (``ok:true``) is distinct from a
    call *failure* (``ok:false``); failures never 500 and never half-write.
    """
    _check_bind_origin_or_abort()
    data = request.get_json(silent=True) or {}
    live_url = (data.get("live_url") or "").strip()
    if not live_url:
        return jsonify({"ok": False, "error_code": "live_url_required"}), 400

    from backlink_publisher.events import EventStore

    store = EventStore()
    record = _published_candidate(store, live_url)
    if record is None:
        return jsonify({"ok": False, "error_code": "not_published"}), 404

    try:
        from backlink_publisher.recheck import events_io
        from backlink_publisher.recheck.probe import recheck_link

        result = recheck_link(record, probe=True, timeout=5.0)
        events_io.emit_recheck(store, [result])
    except Exception as exc:  # noqa: BLE001 — honest failure, never 500, no half-write
        _log.warning("health: scorecard recheck-link failed for %s: %s", live_url, exc)
        return jsonify({"ok": False, "error_code": "probe_failed"}), 200

    return jsonify({
        "ok": True,
        "verdict": result.get("verdict"),
        "live_url": record["live_url"],
        "last_recheck_ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })

# Last-resort body when even rendering the degraded dashboard fails (R5: a GET
# of /ce:health must never 500 — an honest "unavailable" beats a stack trace).
_FALLBACK_HTML = (
    "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
    "<title>Publishing Health</title></head><body>"
    "<main style=\"font-family:system-ui;max-width:40rem;margin:3rem auto;\">"
    "<h1>Publishing Health</h1>"
    "<p>The health dashboard is temporarily unavailable; data may be incomplete. "
    "Please retry shortly.</p><p><a href=\"/\">Home</a></p>"
    "</main></body></html>"
)


def _reconciliation_gaps():
    """Read-only count of reconciler gaps for the dashboard gap banner.

    Returns ``{"pending_checkpoints": int, "quarantine_gaps": int}`` on
    success. Returns ``{}`` on any read error so the dashboard never 500s.
    """
    try:
        from backlink_publisher.checkpoint import list_failed_items
        from backlink_publisher.events.store import EventStore

        pending = len(list_failed_items())
        rows = EventStore().query(
            "SELECT COUNT(*) FROM quarantine_log "
            "WHERE json_extract(raw_payload_json, '$.failure_type') = ?",
            ("reconcile_gap",),
        )
        gaps = int(rows[0][0]) if rows else 0
        return {"pending_checkpoints": pending, "quarantine_gaps": gaps}
    except Exception as exc:  # noqa: BLE001 — never 500 the page
        _log.warning("health: reconciliation gap check failed: %s", exc)
        return {}


def _geo_panel() -> dict:
    """Read-only GEO citation-share panel data (Plan 2026-05-29-006 U9).

    Returns ``{"targets": [<per-target dicts>]}`` on success, or ``{}`` on any
    read error so the health dashboard never 500s (fail-open contract — R5).
    Per-target dicts carry honest state labels matching
    :class:`~backlink_publisher.geo.share.TargetShare` — never a misleading 0%.
    Advisory only; nothing here gates publishing.
    """
    try:
        from backlink_publisher.events import EventStore

        from ..health_metrics import geo_citation_share

        rows = geo_citation_share(EventStore())
        return {"targets": rows} if rows else {}
    except Exception as exc:  # noqa: BLE001 — never 500 the page
        _log.warning("health: geo citation-share read failed: %s", exc)
        return {}


def _decay_counts():
    """Read-only backlink decay counts for the dashboard banner (Plan
    2026-05-29-004 U6). Returns ``{host_gone, link_stripped, dofollow_lost,
    alive, probe_error}`` or ``{}`` on any read error so the page never 500s.
    """
    try:
        from ..health_metrics import decay_counts

        return decay_counts()
    except Exception as exc:  # noqa: BLE001 — never 500 the page
        _log.warning("health: decay count read failed: %s", exc)
        return {}


def _decay_alerts() -> list[dict]:
    """Read decay.alert events from the last 14 days (Plan 2026-06-16-002 U8).

    Returns list of {target_url, lost_count, ts} dicts for the banner.
    Fail-open: any read error → empty list so the page never 500s.
    """
    try:
        from datetime import datetime, timedelta, timezone

        from backlink_publisher.events import EventStore
        from backlink_publisher.events.kinds import DECAY_ALERT

        store = EventStore()
        since = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
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
    except Exception as exc:  # noqa: BLE001 — never 500 the page
        _log.warning("health: decay alerts read failed: %s", exc)
        return []


def _pipeline_summary():
    """Publish counts for past 24h/7d/30d windows + last recheck timestamp.

    Returns a dict with keys ``w24h``, ``w7d``, ``w30d`` (each ``{ok, fail}``)
    and ``last_recheck`` (ISO timestamp or None). Fail-open.
    """
    try:
        import sqlite3
        import time
        from backlink_publisher.config.loader import _config_dir

        db_path = _config_dir() / "events.db"
        if not db_path.exists():
            return {}

        now = time.time()
        windows = {"w24h": now - 86400, "w7d": now - 604800, "w30d": now - 2592000}
        con = sqlite3.connect(str(db_path), timeout=2)
        cur = con.cursor()

        result: dict = {}
        for wname, since_ts in windows.items():
            cur.execute(
                "SELECT json_extract(payload_json, '$.status') as status, COUNT(*) "
                "FROM events WHERE kind IN ('publish.confirmed','publish.unverified','publish.failed') "
                "AND ts_utc >= ? GROUP BY status",
                (since_ts,),
            )
            row_map: dict = {}
            for status, count in cur.fetchall():
                row_map[status or "unknown"] = count
            result[wname] = {
                "ok": row_map.get("published", 0) + row_map.get("ok", 0),
                "fail": sum(v for k, v in row_map.items() if k not in ("published", "ok")),
            }

        # most recent recheck
        cur.execute("SELECT MAX(ts_utc) FROM events WHERE kind='link.rechecked'")
        row = cur.fetchone()
        last_ts = row[0] if row and row[0] else None
        if last_ts:
            import datetime
            result["last_recheck"] = datetime.datetime.fromtimestamp(
                last_ts, tz=datetime.timezone.utc
            ).isoformat()
        else:
            result["last_recheck"] = None

        con.close()
        return result
    except Exception as exc:  # noqa: BLE001
        _log.warning("health: pipeline summary failed: %s", exc)
        return {}


_EVENTS_DB_WARN_MB = 100.0    # warn when events.db exceeds this
_EVENTS_WARN_ROWS = 100_000   # warn when events table row count exceeds this


def _storage_health():
    """Disk usage of events.db, dedup.db, and the config directory.

    Also queries events.db for row counts (events table + articles table) and
    sets ``events_db_warn=True`` when the file exceeds ``_EVENTS_DB_WARN_MB``
    or the events table exceeds ``_EVENTS_WARN_ROWS``.

    Returns ``{events_db_mb, dedup_db_mb, config_dir_mb, events_rows,
    articles_rows, events_db_warn}`` or ``{}`` on error.
    """
    try:
        import os
        import sqlite3
        from backlink_publisher.config.loader import _config_dir

        cfg = _config_dir()

        def _mb(path) -> float:
            try:
                return round(os.path.getsize(path) / 1_048_576, 2)
            except OSError:
                return 0.0

        def _dir_mb(dirpath) -> float:
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
                    events_rows = con.execute(
                        "SELECT COUNT(*) FROM events"
                    ).fetchone()[0]
                    articles_rows = con.execute(
                        "SELECT COUNT(*) FROM articles"
                    ).fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            _log.debug("health: events.db row count failed: %s", exc)

        return {
            "events_db_mb": events_db_mb,
            "dedup_db_mb": _mb(cfg / "dedup.db"),
            "config_dir_mb": _dir_mb(cfg),
            "events_rows": events_rows,
            "articles_rows": articles_rows,
            "events_db_warn": (
                events_db_mb > _EVENTS_DB_WARN_MB
                or events_rows > _EVENTS_WARN_ROWS
            ),
        }
    except Exception as exc:  # noqa: BLE001
        _log.warning("health: storage health failed: %s", exc)
        return {}


@bp.route("/ce:health", methods=["GET"])
def ce_health():
    def _build():
        # U1 backstop first (single-flight, never raises) so the aggregates
        # below read freshened data; then U2 aggregations.
        from ..health_metrics import (
            DEFAULT_WINDOW_DAYS,
            Health,
            SuccessRate,
            _window_start,
            build_health,
        )
        from ..services.health_projection import project_on_read

        projection = project_on_read()
        try:
            health = build_health()
        except Exception as exc:  # noqa: BLE001 — R5: degrade, never 500 the page
            _log.warning("health: aggregation failed, rendering degraded: %s", exc)
            health = Health(
                window_days=DEFAULT_WINDOW_DAYS,
                since_utc=_window_start(
                    datetime.now(timezone.utc), DEFAULT_WINDOW_DAYS
                ),
                success=SuccessRate(),
            )
            projection = dataclasses.replace(
                projection,
                degraded=True,
                degraded_reason=projection.degraded_reason
                or f"{type(exc).__name__}: {exc}",
            )
        return projection, health

    def _canary_rows():
        """Read-side join of canary health (Plan 2026-05-27-001 Unit 4, R16).

        Reads ``canary_health_store.list_all()`` directly — NEVER writes canary
        state into ``channel_status_store`` (bind-scoped). Surfaces only
        non-sensitive fields (platform name, verdict, debounce counts,
        timestamps); no credentials/URLs. Fail-open: any read error → empty
        list so the dashboard never 500s on canary."""
        try:
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
        except Exception as exc:  # noqa: BLE001 — never 500 the page on canary
            _log.warning("health: canary read failed: %s", exc)
            return []

    def _forward_path_rows():
        """Forward-path drift rows for the publish-path canary card.

        Reads ``list_publish_path_all()`` (Plan 2026-05-27-006 Unit 4) —
        the ``_publish_path`` sibling stream in ``canary-health.json``,
        disjoint from the evergreen ``_canary_rows()`` records.
        Advisory-only in v1: ``degraded`` flag shown but no gate.
        Fail-open: any read error → empty list."""
        try:
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
        except Exception as exc:  # noqa: BLE001 — never 500 the page
            _log.warning("health: forward-path read failed: %s", exc)
            return []

    def _scorecard_rows():
        """Per-channel value scorecard card (Plan 2026-06-01-005, Unit 8 MVP).

        Reads the same stores the equity-ledger reads, re-keyed by channel —
        declared registry signals (dofollow / referral_value) beside measured
        liveness, as a signal vector (no composite). The GA4 referral / GSC
        discovery / AI-retrievability axes render as ``inert:not-landed``
        (Wave-0 DESCOPE). Read-only, advisory — never gates publishing.
        Fail-open: any read error → empty list so the dashboard never 500s."""
        try:
            from backlink_publisher.scorecard import build_channel_scorecard

            return [r.to_jsonl_dict() for r in build_channel_scorecard()]
        except Exception as exc:  # noqa: BLE001 — never 500 the page on scorecard
            _log.warning("health: channel scorecard read failed: %s", exc)
            return []

    def _platform_health():
        try:
            from backlink_publisher.config import load_config
            from backlink_publisher.health.aggregate import build_platform_health
            cfg = _g_cache('config', load_config)
            return build_platform_health(cfg)
        except Exception as exc:  # noqa: BLE001 — never 500 the page
            _log.warning("health: platform_health build failed: %s", exc)
            return {}

    def _autopilot_alerts():
        """Sites with alert_pending=True from schedule_store (U8 R3). Fail-open."""
        try:
            import webui_store as _ws
            targets = _ws.schedule_store.load().get("autopilot_targets", {})
            return [
                {"site_url": url, **cfg}
                for url, cfg in targets.items()
                if cfg.get("alert_pending")
            ]
        except Exception:  # noqa: BLE001
            return []

    def _weights_snapshot():
        from ..health_metrics import weights_snapshot
        return weights_snapshot()

    try:
        projection, health = _g_cache("health_agg", _build)
        canary = _g_cache("canary_health", _canary_rows)
        forward_path = _g_cache("forward_path_health", _forward_path_rows)
        reconciliation_gaps = _g_cache("reconciliation_gaps", _reconciliation_gaps)
        recheck_decay = _g_cache("recheck_decay", _decay_counts)
        channel_scorecard = _g_cache("channel_scorecard", _scorecard_rows)
        geo_panel = _g_cache("geo_panel", _geo_panel)
        pipeline_summary = _g_cache("pipeline_summary", _pipeline_summary)
        storage_health = _g_cache("storage_health", _storage_health)
        platform_health = _g_cache("platform_health", _platform_health)
        autopilot_alerts = _autopilot_alerts()
        weights_snap = _g_cache("weights_snapshot", _weights_snapshot)
        decay_alerts = _g_cache("decay_alerts", _decay_alerts)
        return _render(
            "health.html",
            health=health,
            projection=projection,
            canary=canary,
            forward_path=forward_path,
            reconciliation_gaps=reconciliation_gaps,
            recheck_decay=recheck_decay,
            channel_scorecard=channel_scorecard,
            geo_panel=geo_panel,
            pipeline_summary=pipeline_summary,
            storage_health=storage_health,
            platform_health=platform_health,
            autopilot_alerts=autopilot_alerts,
            weights_snapshot=weights_snap,
            decay_alerts=decay_alerts,
            active_page='health',
        )
    except Exception as exc:  # noqa: BLE001 — R5: even a render/context error must not 500
        _log.error("health: dashboard render failed, serving minimal fallback: %s", exc)
        return _FALLBACK_HTML, 200


@bp.route("/health", methods=["GET"])
def health_json():
    """Machine-readable health endpoint (Plan 2026-06-09-001 U3 / R15–R17).

    Returns 200 when healthy, 503 when any channel is expired/unreachable,
    scheduler is not running, or no pipeline run has ever been recorded.
    GET-only — the global CSRF guard skips GET requests, so no token needed.
    ``BACKLINK_PUBLISHER_ALLOW_NETWORK=1`` extends to off-loopback callers.
    """
    from ..services.health_projection import compute_health_json

    payload = compute_health_json()
    status = 200 if payload["healthy"] else 503
    return jsonify(payload), status


@bp.route("/health/alerts", methods=["GET"])
def health_alerts():
    """Return active alerts (Plan U4.3). GET-only, no CSRF needed."""
    return jsonify({
        "active": alert_registry.to_dicts(only_active=True),
        "count": len(alert_registry.active()),
    })
