from __future__ import annotations

from datetime import UTC
import logging
import re
from typing import Any

from flask import Blueprint, jsonify, redirect, url_for

from backlink_publisher._util.errors import UsageError

from ..helpers.contexts import _render
from ..services.keepalive_job import registry as keepalive_registry

bp = Blueprint("command_center", __name__)

_log = logging.getLogger(__name__)

#: Process-global (module-level, NOT per-request) record of the last time each
#: new-style signal source (Plan 2026-07-06-004 Unit 2, R15) successfully
#: refreshed. Powers the "上次更新于 HH:MM" vs "从未成功加载" distinction on a
#: fail-open degrade -- the original 4 subsystems only ever show a flat "状态
#: 不可用" (no timestamp), so this is new copy for the two new sources only,
#: not a retrofit of the older cards.
_LAST_SUCCESS_AT: dict[str, str] = {}


def _mark_signal_success(key: str) -> None:
    from datetime import datetime
    _LAST_SUCCESS_AT[key] = datetime.now().strftime("%H:%M")


def _signal_unavailable_message(key: str, label: str) -> str:
    """Build "无法加载{label}" + either a last-known-good time or "从未成功加载"."""
    ts = _LAST_SUCCESS_AT.get(key)
    if ts:
        return f"无法加载{label}，上次更新于 {ts}"
    return f"无法加载{label}，从未成功加载"


def _friendly_error(msg: str) -> str:
    """Truncate noisy Python paths from error messages."""
    msg = re.sub(r"\([^)]*\.py[^)]*\)", "", msg)
    msg = re.sub(r"/[^\s]+\.py", "", msg)
    return msg.strip().rstrip(",").strip()


#: Cache key for the whole-aggregator TTL wrap below. A single fixed key (not
#: per-request/per-user — this is a single-operator local tool) is deliberate:
#: every poll/tab within the TTL window collapses onto the same cached dict.
_SUBSYSTEM_STATUS_CACHE_KEY = "command_center._collect_subsystem_status"

#: Plan 2026-07-06-004 K10: `_g_cache` (webui_app/helpers/_request_cache.py)
#: only dedupes reads *within* one HTTP request — it does nothing for polling
#: (each poll is a fresh request) or several browser tabs polling at once.
#: `history_store.load()` below (full JSON parse + a per-item 24h/7d scan) and
#: `list_scheduled()`'s `drafts_store.load()` (unindexed full-table scan) are
#: unbounded-cost reads that scale with poll frequency, so the whole aggregate
#: is wrapped in the SAME process-wide TTL cache `OptimizationState.load()`
#: already uses (`_ttl_cache_get`/`_ttl_cache_set`), not a new caching layer or
#: push/SSE mechanism (both explicitly rejected in the origin requirements
#: doc). 4 seconds (plan's 3-5s band) — short enough that an action followed
#: immediately by a read-back still feels live, long enough that a burst of
#: concurrent polls/tabs collapses into one real query.
_SUBSYSTEM_STATUS_TTL_SECONDS = 4.0


def _collect_subsystem_status() -> Any:
    """Aggregate a lightweight snapshot from each monitored subsystem.

    Returns a dict with top-level keys (keepalive, equity, optimization,
    history, credentials, error_reports, schedule_queue) that the template
    sections / card builder read to render their cards. Never raises — every
    section degrades to "unavailable" on error. Cross-request TTL-cached (see
    ``_SUBSYSTEM_STATUS_TTL_SECONDS`` above) so repeated calls within the TTL
    window (polling, multiple tabs) hit the underlying stores at most once.
    """
    from backlink_publisher._util.cache import _ttl_cache_get, _ttl_cache_set

    cached = _ttl_cache_get(_SUBSYSTEM_STATUS_CACHE_KEY)
    if cached is not None:
        return cached

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

    # ── error-reports backlog (new 5th signal source, R5) — own try/except
    # lives inside _collect_error_reports_status() itself, not here, so it
    # never shares a try/except with any other subsystem.
    result["error_reports"] = _collect_error_reports_status()

    # ── schedule/queue backlog (new 6th signal source, R6) — same isolation.
    result["schedule_queue"] = _collect_schedule_queue_status()

    _ttl_cache_set(_SUBSYSTEM_STATUS_CACHE_KEY, result, ttl=_SUBSYSTEM_STATUS_TTL_SECONDS)
    return result


#: "First N" items surfaced inline on a hybrid card before falling back to a
#: "查看全部" deep-link (Plan 2026-07-06-004 Unit 2 K1). No existing
#: `.data-table` component in this repo paginates (frontend/src/pages/*
#: tables all render the full array with no page-size constant — verified
#: against History/Schedule/Sites pages), so there is no existing convention
#: to mirror; 5 is picked as "one glance, no scroll" for a card meant to stay
#: secondary to the aggregate headline, not become a full list view.
_ERROR_REPORTS_TOP_N = 5
_SCHEDULE_QUEUE_TOP_N = 5

#: Fixed vocabulary for a queue task's live ``status`` column. Only
#: pending/failed should ever reach here (``get_runnable()``'s own SQL WHERE
#: already restricts to these two), but the scheduler thread can flip a task
#: to ``processing`` between that read and this loop — see
#: ``_classify_queue_task``'s docstring.
_QUEUE_STATUS_BUCKETS = {"pending", "failed"}


def _collect_error_reports_status() -> dict:
    """5th signal source (R5): open frontend-error-report backlog.

    Reads ``webui_store.error_reports.error_report_store`` directly (mirrors
    how ``webui_store.channel_status`` is read above) rather than going
    through an HTTP round-trip. Own try/except — isolated from every other
    subsystem/signal source, matching the existing fail-open pattern; a
    failure here must never affect the other 5 sources' cards.
    """
    try:
        from webui_store.error_reports import error_report_store
        reports = error_report_store.list(filters={"status": "open"})
        # Most-urgent first: highest occurrence count, ties broken by most
        # recently seen. Two stable sorts (secondary key first) avoid sign
        # juggling a single composite key would need for "both descending".
        reports = sorted(reports, key=lambda r: r.get("last_seen_at") or "", reverse=True)
        reports.sort(key=lambda r: -(r.get("occurrences") or 0))
        status = {"open_count": len(reports), "items": reports[:_ERROR_REPORTS_TOP_N]}
        _mark_signal_success("error_reports")
        return status
    except Exception:
        return {"error": _signal_unavailable_message("error_reports", "错误回报")}


def _classify_queue_task(task: dict) -> str:
    """Bucket one queue task by its live ``status``: 'pending' | 'failed' | 'other'.

    ``get_runnable()``'s own SQL only returns pending/failed rows, so 'other'
    should never fire in practice — but the background scheduler thread
    (``webui_app/scheduler.py::_process_queue_job``) can flip a task to
    'processing' concurrently, between that query and this loop. Per the
    status-vocabulary-drift lesson (docs/solutions/logic-errors/projector-
    silent-drop-status-vocabulary-drift-2026-05-26.md), an unrecognized value
    must be logged and still counted (bucket 'other'), not silently dropped
    from the total.
    """
    status = task.get("status") or ""
    if status not in _QUEUE_STATUS_BUCKETS:
        _log.warning(
            "schedule_queue signal: unrecognized queue task status %r (task id=%s)",
            status, task.get("id"),
        )
        return "other"
    return status


def _classify_scheduled_draft(item: dict, now) -> str:
    """Bucket one scheduled draft: 'overdue' | 'upcoming' | 'unscheduled'.

    'overdue' means ``scheduled_at`` has already passed but the draft is
    still sitting in ``status == 'scheduled'`` — the "stuck" case the plan's
    Approach section calls out. A missing or unparseable ``scheduled_at``
    can't be time-compared, so it is counted under 'unscheduled' (logged)
    rather than dropped — same log-and-count discipline as
    ``_classify_queue_task``.
    """
    from datetime import datetime
    scheduled_at = item.get("scheduled_at")
    if not scheduled_at:
        _log.warning(
            "schedule_queue signal: scheduled draft %s missing scheduled_at",
            item.get("id"),
        )
        return "unscheduled"
    try:
        due = datetime.fromisoformat(scheduled_at)
    except (ValueError, TypeError):
        _log.warning(
            "schedule_queue signal: scheduled draft %s has unparseable scheduled_at=%r",
            item.get("id"), scheduled_at,
        )
        return "unscheduled"
    if due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    return "overdue" if due <= now else "upcoming"


#: Urgency rank for merged schedule/queue items (lower sorts first). Overdue
#: drafts and failed queue tasks are equally the most actionable; 'other' is
#: a drift bucket that should still surface, so it is not last.
_SCHEDULE_QUEUE_URGENCY = {
    "overdue": 0, "failed": 0, "pending": 1, "other": 1, "unscheduled": 1, "upcoming": 2,
}


def _collect_schedule_queue_status() -> dict:
    """6th signal source (R6): stuck/upcoming scheduled drafts + pending/failed
    queue retries, merged into ONE signal source (Plan 2026-07-06-004 Unit 2
    Approach: "两者合并为一张聚合卡...实作时依前 N 值决定"). Kept as a single
    merged card rather than two: both sources answer the same operator
    question ("what's waiting on a clock right now"), and splitting them would
    add a second near-empty card for what is normally a quiet signal.

    Own try/except, isolated from the other 5 sources. Deliberately a SINGLE
    try/except around both underlying reads (``list_scheduled()`` over
    drafts_store, ``queue_store.get_runnable()``) rather than one each: this
    source is defined as one merged card, so a partial success (one read ok,
    the other failing) would misreport the merged total — better to degrade
    the whole card than show a silently-incomplete count.
    """
    try:
        from datetime import datetime

        from webui_store import queue_store

        from ..api.scheduled_api import list_scheduled

        now = datetime.now(UTC)

        sched_result = list_scheduled()
        if not sched_result.get("ok", True):
            raise RuntimeError(sched_result.get("error") or "list_scheduled() failed")
        drafts = sched_result.get("items", [])
        tasks = queue_store.get_runnable()

        counts = {"overdue": 0, "upcoming": 0, "unscheduled": 0, "pending": 0, "failed": 0, "other": 0}
        items: list[dict] = []

        for draft in drafts:
            bucket = _classify_scheduled_draft(draft, now)
            counts[bucket] += 1
            items.append({
                "id": draft.get("id", ""),
                "item_type": "scheduled_draft",
                "status": bucket,
                "headline": draft.get("target_url") or "",
                "detail": draft.get("scheduled_at") or "",
            })

        for task in tasks:
            bucket = _classify_queue_task(task)
            counts[bucket] += 1
            urls = task.get("urls") or []
            platform = (task.get("config") or {}).get("platform", "")
            items.append({
                "id": task.get("id", ""),
                "item_type": "queue_task",
                "status": bucket,
                "headline": urls[0] if urls else platform,
                "detail": task.get("error") or task.get("next_retry_at") or "",
            })

        items.sort(key=lambda it: _SCHEDULE_QUEUE_URGENCY.get(it["status"], 1))

        status = {
            "n_overdue": counts["overdue"],
            "n_upcoming": counts["upcoming"],
            "n_unscheduled": counts["unscheduled"],
            "n_pending": counts["pending"],
            "n_failed": counts["failed"],
            "n_other": counts["other"],
            "total": len(items),
            "items": items[:_SCHEDULE_QUEUE_TOP_N],
        }
        _mark_signal_success("schedule_queue")
        return status
    except Exception:
        return {"error": _signal_unavailable_message("schedule_queue", "排程/队列")}


def _any_subsystem_error(status: dict) -> bool:
    """True when at least one subsystem in ``status`` reported a caught error.

    ``_collect_subsystem_status()`` isolates every subsystem in its own
    try/except and swaps in ``{"error": ...}`` on failure (see its
    docstring) rather than ever propagating the exception — so a single
    bad source degrades only its own card instead of dragging down the
    whole aggregator. That per-subsystem isolation must not also *erase*
    the fact that something failed at the top level (R18): before this
    fix, the aggregator's ``degraded`` flag only flipped true when the
    entire aggregator crashed, so a source that quietly caught its own
    exception left the "everything's fine" banner showing even though its
    card had degraded to an 'unavailable' state.
    """
    return any(
        isinstance(sub, dict) and "error" in sub
        for sub in status.values()
    )


# Severity → sort rank (lower = more urgent / more prominent). Used by the
# monitor hub to rank cards and drive their visual weight ("today's anomalies
# first"). Plan priority: credential-failure > stale/dead links > equity gaps.
_SEVERITY_RANK = {"danger": 0, "warning": 1, "ok": 2, "info": 2}


def _sub_err(sub: dict) -> str | None:
    """Return a subsystem's caught-error message, or ``None`` if it's healthy.

    Module-level (was a closure inside ``_build_anomaly_cards`` before Unit 2)
    so the new hybrid-card builders below can share it too.
    """
    return sub.get("error") if isinstance(sub, dict) else None


def _build_anomaly_cards(status: dict) -> list[dict]:
    """Turn the raw subsystem snapshot into severity-ranked monitor-hub cards.

    Each card: {key, title, severity, headline, detail, deep_link, action},
    plus an optional ``items`` list on the two hybrid cards (error_reports,
    schedule_queue — Plan 2026-07-06-004 Unit 2 K1). Cards are sorted
    most-urgent first; danger cards render with the heaviest visual weight in
    the template. A subsystem that errored degrades to an 'unavailable' info
    card rather than vanishing.
    """
    cards: list[dict] = []
    _err = _sub_err

    # 1. Credentials (top priority)
    cred = status.get("credentials", {})
    if _err(cred):
        cards.append(_card("credentials", "渠道凭证", "info", "状态不可用", _err(cred), "/settings", None))
    else:
        n = cred.get("failed_count", 0)
        failed = cred.get("failed", [])
        if n:
            # `failed_channels` (Plan 2026-07-06-004 Unit 6): the plain-text
            # `detail` above ("、".join(...)) is fine for display but not
            # machine-usable — the SPA needs the raw channel-name list to
            # render one "重新验证" button per failed channel. Minimal
            # structured-data addition alongside the existing formatted
            # string; no other card gets this field.
            cards.append(_card("credentials", "渠道凭证", "danger",
                               f"{n} 个渠道凭证失效", "、".join(failed),
                               "/settings", {"label": "去设置", "href": "/settings"},
                               failed_channels=failed))
        else:
            cards.append(_card("credentials", "渠道凭证", "ok",
                               f"{cred.get('n_bound', 0)} 个渠道已绑定", "凭证健康", "/settings", None,
                               failed_channels=[]))

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

    # 5. Error-reports backlog (hybrid card, R5)
    cards.append(_build_error_reports_card(status.get("error_reports", {})))

    # 6. Schedule/queue backlog (hybrid card, R6)
    cards.append(_build_schedule_queue_card(status.get("schedule_queue", {})))

    cards.sort(key=lambda c: _SEVERITY_RANK.get(c["severity"], 3))
    return cards


def _error_report_item(report: dict) -> dict:
    """Shrink one full error-report dict to the fields a hybrid-card item needs.

    ``report`` is whatever Unit 1 of the frontend-error-reporting plan
    sanitized and stored — free-form beyond the store's own mirrored columns
    (id/status/severity/occurrences/last_seen_at), so ``headline`` falls back
    across a few plausible keys rather than assuming one exact field name.
    """
    headline = report.get("message") or report.get("title") or report.get("source") or "错误回报"
    return {
        "id": report.get("id", ""),
        "item_type": "error_report",
        "status": report.get("status", "open"),
        "severity": report.get("severity"),
        "occurrences": report.get("occurrences", 1),
        "headline": str(headline)[:200],
        "detail": report.get("last_seen_at") or "",
    }


def _build_error_reports_card(er: dict) -> dict:
    """Card 5: open frontend-error-report backlog (hybrid — R5).

    Always renders (even at 0 open reports — "0 条，健康", not an absent
    card, per the plan's explicit edge case) and always carries an ``items``
    list (possibly empty), which is what distinguishes a hybrid card from the
    original 4 plain aggregate cards.
    """
    if _sub_err(er):
        return _card("error_reports", "错误回报", "info", "状态不可用",
                     _sub_err(er), "/error-reports", None)

    n = er.get("open_count", 0)
    items = er.get("items", [])
    if not n:
        return _card("error_reports", "错误回报", "ok", "0 条，健康",
                     "没有待处理的错误回报", "/error-reports", None, items=[])

    action = {"label": "查看全部", "href": "/error-reports"} if n > len(items) else None
    return _card("error_reports", "错误回报", "warning", f"{n} 条待处理",
                 f"共 {n} 笔开放中的错误回报", "/error-reports", action,
                 items=[_error_report_item(r) for r in items])


_SCHEDULE_QUEUE_LABELS = {
    "overdue": "卡住排程", "upcoming": "即将发布", "unscheduled": "排程时间不明",
    "pending": "待重试", "failed": "重试失败", "other": "状态异常",
}


def _build_schedule_queue_card(sq: dict) -> dict:
    """Card 6: stuck/upcoming scheduled drafts + pending/failed queue retries
    (hybrid — R6). Same always-renders-with-items contract as the error-reports
    card above.
    """
    if _sub_err(sq):
        return _card("schedule_queue", "排程/队列", "info", "状态不可用",
                     _sub_err(sq), "/schedule", None)

    total = sq.get("total", 0)
    items = sq.get("items", [])
    if not total:
        return _card("schedule_queue", "排程/队列", "ok", "0 项，健康",
                     "没有卡住的排程或待重试的队列任务", "/schedule", None, items=[])

    n_urgent = sq.get("n_overdue", 0) + sq.get("n_failed", 0)
    sev = "warning" if n_urgent else "info"
    detail = (
        f"{_SCHEDULE_QUEUE_LABELS['overdue']} {sq.get('n_overdue', 0)} · "
        f"{_SCHEDULE_QUEUE_LABELS['pending']} {sq.get('n_pending', 0)} · "
        f"{_SCHEDULE_QUEUE_LABELS['failed']} {sq.get('n_failed', 0)} · "
        f"{_SCHEDULE_QUEUE_LABELS['upcoming']} {sq.get('n_upcoming', 0)}"
    )
    action = {"label": "查看全部", "href": "/schedule"} if total > len(items) else None
    return _card("schedule_queue", "排程/队列", sev, f"{total} 项待处理", detail,
                 "/schedule", action, items=items)


def _card(key, title, severity, headline, detail, deep_link, action, items=None, **extra):
    card = {
        "key": key, "title": title, "severity": severity,
        "headline": headline, "detail": detail or "",
        "deep_link": deep_link, "action": action,
    }
    if items is not None:
        card["items"] = items
    # `**extra` (Plan 2026-07-06-004 Unit 6): a narrow escape hatch for a
    # single card-specific field (currently only credentials' `failed_channels`)
    # rather than threading a new named parameter through every call site.
    card.update(extra)
    return card


@bp.route("/ce:command-center", methods=["GET"])
def command_center() -> Any:
    status = _collect_subsystem_status()
    return _render("command_center.html", status=status, active_page="command_center")


@bp.route("/monitor-hub", methods=["GET"])
def monitor_hub() -> Any:
    """Redirect legacy /monitor-hub → SPA /app/ (P15 B4).

    Plan 2026-07-06-004 Unit 4 / K7: kept as a permanent alias for existing
    bookmarks/links, but its target changed. Monitor moved from '/monitor' to
    '/' (the new SPA homepage), so this must redirect to the new homepage
    (subpath="") rather than the now-stale '/app/monitor' — that path's
    content meaning changed with the swap, it does not still show the
    monitor-hub view a bookmark holder expects.
    """
    return redirect(url_for("spa.spa", subpath=""), 302)


@bp.route("/monitor-hub/jinja", methods=["GET"])
def monitor_hub_jinja() -> Any:
    """Legacy Jinja fallback — kept for LITE mode."""
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
