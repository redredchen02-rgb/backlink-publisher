from __future__ import annotations

from datetime import UTC
import re
from typing import Any

from flask import Blueprint, jsonify

from backlink_publisher._util.errors import UsageError

from ..helpers.contexts import _render
from ..services.keepalive_job import registry as keepalive_registry

bp = Blueprint("command_center", __name__)


def _friendly_error(msg: str) -> str:
    """Truncate noisy Python paths from error messages."""
    msg = re.sub(r"\([^)]*\.py[^)]*\)", "", msg)
    msg = re.sub(r"/[^\s]+\.py", "", msg)
    return msg.strip().rstrip(",").strip()


def _collect_subsystem_status() -> Any:
    """Aggregate a lightweight snapshot from each monitored subsystem.

    Returns a dict with top-level keys (keepalive, equity, optimization, history)
    that the template sections read to render their cards. Never raises — every
    section degrades to "unavailable" on error.
    """
    result = {}

    # ── keep-alive ──────────────────────────────────────────────────────
    try:
        from ..services.keep_alive import build_keepalive_view
        view = build_keepalive_view()
        result["keepalive"] = {
            "n_targets": len(view.get("targets", [])),
            "stripped": view.get("stripped_count", 0),
            "alive": view.get("alive_count", 0),
            "unknown": view.get("unknown_count", 0),
        }
    except Exception as exc:
        result["keepalive"] = {"error": _friendly_error(str(exc))}

    # ── running jobs ────────────────────────────────────────────────────
    jobs = []
    try:
        for kind in ("recheck", "republish", "gap_closure"):
            j = keepalive_registry.running_job(kind)
            if j:
                jobs.append(j)
        result["jobs"] = jobs
    except Exception as exc:
        result["jobs"] = {"error": _friendly_error(str(exc))}

    # ── equity — derived from optimization state (no ledger_store) ──────
    try:
        from backlink_publisher.optimization import OptimizationState as _OS
        _eq_state = _OS()
        _eq_summary = _eq_state.to_summary()
        platforms = _eq_summary.get("platforms", [])
        low_weight = [p for p in platforms if (p.get("current") or p.get("weight") or 0) < 0.3]
        result["equity"] = {
            "total_rows": len(platforms),
            "low_weight_count": len(low_weight),
        }
    except Exception as exc:
        result["equity"] = {"error": _friendly_error(str(exc))}

    # ── optimization state ──────────────────────────────────────────────
    try:
        from backlink_publisher.optimization import OptimizationState
        state = OptimizationState()
        summary = state.to_summary()
        result["optimization"] = {
            "n_platforms": len(summary.get("platforms", [])),
            "platforms": summary.get("platforms", []),
        }
    except Exception as exc:
        result["optimization"] = {"error": _friendly_error(str(exc))}

    # ── history (recent publish count) ──────────────────────────────────
    try:
        from datetime import datetime, timedelta

        from webui_store import history_store
        hist = history_store.load()
        now = datetime.now(UTC)
        cutoff_24h = (now - timedelta(hours=24)).isoformat()[:16]
        cutoff_7d  = (now - timedelta(days=7)).isoformat()[:10]
        def _ts(h: Any) -> Any:
            return h.get("created_at") or h.get("published_at") or ""
        recent_24h = sum(1 for h in hist if _ts(h) >= cutoff_24h)
        recent_7d  = sum(1 for h in hist if _ts(h)[:10] >= cutoff_7d)
        last_ts = max((_ts(h) for h in hist if _ts(h)), default=None)
        result["history"] = {
            "total": len(hist),
            "recent_24h": recent_24h,
            "recent_7d": recent_7d,
            "last_published_at": (last_ts or "")[:10] or None,
        }
    except Exception as exc:
        result["history"] = {"error": _friendly_error(str(exc))}

    # ── channel credentials (top-priority anomaly: expired/mismatch) ─────
    try:
        from webui_store.channel_status import list_all
        statuses = list_all()
        failed = sorted(
            name for name, rec in statuses.items()
            if (rec.get("status") or "") in ("expired", "identity_mismatch")
        )
        result["credentials"] = {
            "n_bound": sum(1 for r in statuses.values() if (r.get("status") or "") != "unbound"),
            "failed": failed,
            "failed_count": len(failed),
        }
    except Exception as exc:
        result["credentials"] = {"error": _friendly_error(str(exc))}

    return result


# Severity → sort rank (lower = more urgent / more prominent). Used by the
# monitor hub to rank cards and drive their visual weight ("today's anomalies
# first"). Plan priority: credential-failure > stale/dead links > equity gaps.
_SEVERITY_RANK = {"danger": 0, "warning": 1, "ok": 2, "info": 2}


def _build_anomaly_cards(status: dict) -> list[dict]:
    """Turn the raw subsystem snapshot into severity-ranked monitor-hub cards.

    Each card: {key, title, severity, headline, detail, deep_link, action}.
    Cards are sorted most-urgent first; danger cards render with the heaviest
    visual weight in the template. A subsystem that errored degrades to an
    'unavailable' info card rather than vanishing.
    """
    cards: list[dict] = []

    def _err(sub: dict) -> str | None:
        return sub.get("error") if isinstance(sub, dict) else None

    # 1. Credentials (top priority)
    cred = status.get("credentials", {})
    if _err(cred):
        cards.append(_card("credentials", "渠道凭证", "info", "状态不可用", _err(cred), "/settings", None))
    else:
        n = cred.get("failed_count", 0)
        if n:
            cards.append(_card("credentials", "渠道凭证", "danger",
                               f"{n} 个渠道凭证失效", "、".join(cred.get("failed", [])),
                               "/settings", {"label": "去设置", "href": "/settings"}))
        else:
            cards.append(_card("credentials", "渠道凭证", "ok",
                               f"{cred.get('n_bound', 0)} 个渠道已绑定", "凭证健康", "/settings", None))

    # 2. Keep-alive / link liveness
    ka = status.get("keepalive", {})
    if _err(ka):
        cards.append(_card("keepalive", "保活", "info", "状态不可用", _err(ka), "/ce:keep-alive", None))
    else:
        stripped = ka.get("stripped", 0)
        sev = "danger" if stripped else "ok"
        head = f"{stripped} 条链接已失效" if stripped else f"{ka.get('alive', 0)} 条链接存活"
        cards.append(_card("keepalive", "保活", sev, head,
                           f"目标 {ka.get('n_targets', 0)} · 未知 {ka.get('unknown', 0)}",
                           "/ce:keep-alive",
                           {"label": "查看保活", "href": "/ce:keep-alive"} if stripped else None))

    # 3. Equity gaps (low-weight platforms as the gap signal)
    eq = status.get("equity", {})
    if _err(eq):
        cards.append(_card("equity", "权益", "info", "状态不可用", _err(eq), "/ce:equity-ledger", None))
    else:
        low = eq.get("low_weight_count", 0)
        sev = "warning" if low else "ok"
        head = f"{low} 个低权重渠道" if low else "权益分布正常"
        cards.append(_card("equity", "权益", sev, head, f"共 {eq.get('total_rows', 0)} 渠道",
                           "/ce:equity-ledger",
                           {"label": "查看权益", "href": "/ce:equity-ledger"} if low else None))

    # 4. Publish activity (informational)
    hist = status.get("history", {})
    if not _err(hist):
        cards.append(_card("history", "发布活动", "info",
                           f"24h {hist.get('recent_24h', 0)} 篇", f"7天 {hist.get('recent_7d', 0)} 篇",
                           "/ce:history", None))

    cards.sort(key=lambda c: _SEVERITY_RANK.get(c["severity"], 3))
    return cards


def _card(key: Any, title: Any, severity: Any, headline: Any, detail: Any, deep_link: Any, action: Any) -> Any:
    return {
        "key": key, "title": title, "severity": severity,
        "headline": headline, "detail": detail or "",
        "deep_link": deep_link, "action": action,
    }


@bp.route("/ce:command-center", methods=["GET"])
def command_center() -> Any:
    status = _collect_subsystem_status()
    return _render("command_center.html", status=status, active_page="command_center")


@bp.route("/monitor-hub", methods=["GET"])
def monitor_hub() -> Any:
    """Console monitor hub — 'today's anomalies first' aggregated card view."""
    return _render("monitor_hub.html", active_page="monitor_hub")


@bp.route("/api/monitor-hub", methods=["GET"])
def monitor_hub_json() -> Any:
    """Single fail-open aggregation feed for the monitor hub (U5).

    Extends the existing _collect_subsystem_status() aggregator (keepalive /
    equity / optimization / history / credentials) and ranks it into anomaly
    cards. Never 500s — each subsystem already degrades to an 'unavailable'
    card. anomaly_count = cards needing attention (danger + warning).
    """
    try:
        status = _collect_subsystem_status()
        cards = _build_anomaly_cards(status)
    except Exception as exc:  # belt-and-suspenders; aggregator is already fail-open
        return jsonify({"ok": False, "error": _friendly_error(str(exc)), "cards": [], "anomaly_count": 0})
    anomaly_count = sum(1 for c in cards if c["severity"] in ("danger", "warning"))
    return jsonify({"ok": True, "cards": cards, "anomaly_count": anomaly_count})


@bp.route("/ce:command-center/gap-closure", methods=["POST"])
def trigger_gap_closure() -> Any:
    """Trigger a full-pipeline gap-closure run in the background."""
    try:
        job = keepalive_registry.start_gap_closure()
        return jsonify({"status": "started", "job_id": job.id}), 202
    except UsageError as exc:
        running = keepalive_registry.running_job("gap_closure")
        return jsonify({
            "status": "running",
            "job_id": running["job_id"] if running else None,
            "message": str(exc),
        }), 409


@bp.route("/ce:command-center/jobs", methods=["GET"])
def list_jobs() -> Any:
    """Return all tracked jobs across kinds."""
    jobs_by_kind = {}
    for kind in ("recheck", "republish", "gap_closure"):
        try:
            j = keepalive_registry.running_job(kind)
            if j:
                jobs_by_kind[kind] = j
        except Exception:
            pass
    return jsonify(jobs_by_kind)


@bp.route("/ce:command-center/job/<job_id>", methods=["GET"])
def poll_job(job_id: str) -> Any:
    """Poll a specific job by id."""
    result = keepalive_registry.poll(job_id)
    if result is None:
        return jsonify({"error": "job not found"}), 404
    return jsonify(result)
