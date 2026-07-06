"""/sites/* — Plan Unit 3.

R2 (Unit 8): /sites/run and /sites/run/<id>/result are collapsed into
the keep-alive flow — both redirect to /ce:keep-alive.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any
from urllib.parse import quote as _quote

from flask import Blueprint, jsonify, redirect, render_template, request

from backlink_publisher._util.errors import InputValidationError
from backlink_publisher._util.logger import plan_logger
from backlink_publisher._util.url import validate_https_url, validate_main_domain_url
from backlink_publisher.config import (
    DEFAULT_WORK_TEMPLATES,
    load_config,
    save_config,
    ThreeUrlConfig,
)
from backlink_publisher.content.scraper import fetch_work_metadata

from ..helpers._request_cache import _g_cache
from ..helpers.security import _ensure_csrf_token
from ..helpers.url_meta import (
    _derive_branded_pool,
    _derive_exact_pool,
    _derive_partial_pool,
    _verify_urls_or_error,
    fetch_full_tdk,
)
from ..services.work_themed_service import parse_lines as _parse_lines

bp = Blueprint("sites", __name__)


@bp.route("/sites", methods=["GET"])
def sites_form() -> Any:
    csrf_token = _ensure_csrf_token()
    cfg = _g_cache('config', load_config)
    domain_query = (request.args.get("domain") or "").rstrip("/")
    saved = request.args.get("saved", "")
    autofilled_raw = request.args.get("autofilled", "")
    autofilled = [f for f in autofilled_raw.split(",") if f.strip()] if autofilled_raw else []

    form: dict = {}
    if domain_query:
        entry = cfg.target_three_url.get(domain_query)
        if entry is not None:
            form = {
                "main_url": entry.main_url,
                "list_url": entry.list_url,
                "work_urls": "\n".join(entry.work_urls),
                "branded_pool": "\n".join(entry.branded_pool),
                "partial_pool": "\n".join(entry.partial_pool),
                "exact_pool": "\n".join(entry.exact_pool),
                "work_anchor_templates": "\n".join(entry.work_anchor_templates),
                "count": "10",
                "insecure_tls": entry.insecure_tls,
            }

    # all_sites: list of {label, main_url, autopilot_enabled, autopilot_interval,
    #                      alert_pending, next_run_time_iso}
    import sys as _sys

    import webui_store as _ws
    sched_settings = _ws.schedule_store.load()
    autopilot_targets = sched_settings.get("autopilot_targets", {})
    _sched_mod = _sys.modules.get('webui_app.scheduler')
    all_sites = []
    for label, entry in sorted(cfg.target_three_url.items()):
        ap_cfg = autopilot_targets.get(entry.main_url, {})
        ap_enabled = bool(ap_cfg.get("enabled", False))
        next_run_time_iso = None
        if ap_enabled and _sched_mod is not None and getattr(_sched_mod, '_scheduler', None) is not None:
            _job_id = _sched_mod._autopilot_job_id(entry.main_url)
            try:
                _job = _sched_mod._scheduler.get_job(_job_id)
            except Exception:
                _job = None
            if _job is not None and _job.next_run_time is not None:
                next_run_time_iso = _job.next_run_time.isoformat()
        all_sites.append({
            "label": label,
            "main_url": entry.main_url,
            "autopilot_enabled": ap_enabled,
            "autopilot_interval": int(ap_cfg.get("interval_seconds", 86400)),
            "alert_pending": bool(ap_cfg.get("alert_pending", False)),
            "next_run_time_iso": next_run_time_iso,
        })

    return render_template(
        "sites.html",
        csrf_token=csrf_token,
        form=form,
        errors={},
        saved=saved,
        autofilled=autofilled,
        flash_type=request.args.get("flash_type"),
        flash_msg=request.args.get("flash_msg"),
        default_templates=", ".join(DEFAULT_WORK_TEMPLATES),
        active_page='sites',
        all_sites=all_sites,
        plan_gap_summary=_plan_gap_summary(),
        citation_share_alert=_citation_share_alert(),
    )


def _validate_three_url_fields(raw: dict) -> tuple[dict | None, dict[str, str]]:
    """Validate four URL fields + gate checks. Returns (validated_data, errors).

    validated_data is None when there are any errors.
    """
    errors: dict[str, str] = {}

    main_url = validate_main_domain_url(str(raw["main_url"]))
    if not main_url:
        errors["main_url"] = "必须 https + host-root + 单一尾斜杠（例：https://your-site.com/）"

    list_url: str = ""
    if str(raw["list_url"]):
        validated = validate_https_url(str(raw["list_url"]))
        if not validated:
            errors["list_url"] = "必须 https"
        else:
            list_url = validated

    work_urls_raw = _parse_lines(str(raw["work_urls"]))
    work_urls: list[str] = []
    bad_work: list[str] = []
    for u in work_urls_raw:
        normalized = validate_https_url(u)
        if normalized:
            work_urls.append(normalized)
        else:
            bad_work.append(u)
    if bad_work:
        errors["work_urls"] = f"以下 URL 必须 https：{', '.join(bad_work)}"

    branded_pool = _parse_lines(str(raw["branded_pool"]))
    partial_pool = _parse_lines(str(raw["partial_pool"]))
    exact_pool = _parse_lines(str(raw["exact_pool"]))
    templates = _parse_lines(str(raw["work_anchor_templates"])) or list(DEFAULT_WORK_TEMPLATES)

    if main_url and "main_url" not in errors:
        _, gate_err = _verify_urls_or_error([main_url], "main_url")
        if gate_err:
            errors["main_url"] = gate_err
    if list_url and "list_url" not in errors:
        _, gate_err = _verify_urls_or_error([list_url], "list_url")
        if gate_err:
            errors["list_url"] = gate_err
    if work_urls and "work_urls" not in errors:
        _, gate_err = _verify_urls_or_error(work_urls, "work_urls")
        if gate_err:
            errors["work_urls"] = gate_err

    if errors:
        return None, errors

    return {
        "main_url": main_url,
        "list_url": list_url,
        "work_urls": work_urls,
        "branded_pool": branded_pool,
        "partial_pool": partial_pool,
        "exact_pool": exact_pool,
        "templates": templates,
        "insecure_tls": bool(raw.get("insecure_tls")),
    }, {}


def _derive_three_url_fields(data: dict) -> tuple[dict, list[str]]:
    """Server-side derivation of empty three-URL fields. Returns (enriched, fields_derived)."""
    main_url = data["main_url"]
    branded_pool = data["branded_pool"]
    partial_pool = data["partial_pool"]
    exact_pool = data["exact_pool"]
    work_urls = data["work_urls"]
    list_url = data["list_url"]
    fields_derived: list[str] = []

    tdk: dict | None = None
    if not branded_pool or not partial_pool:
        try:
            tdk = fetch_full_tdk(main_url)
        except Exception as exc:
            plan_logger.warn("tdk_fetch_failed", url=main_url, reason=type(exc).__name__)

    if not list_url:
        assert main_url is not None
        list_url = main_url
        fields_derived.append("list_url")
    if not branded_pool:
        assert main_url is not None
        branded_pool = _derive_branded_pool(main_url, tdk)
        fields_derived.append("branded_pool")
    if not partial_pool:
        assert main_url is not None
        partial_pool = _derive_partial_pool(main_url, tdk)
        fields_derived.append("partial_pool")
    if not exact_pool:
        assert main_url is not None
        exact_pool = _derive_exact_pool(main_url)
        fields_derived.append("exact_pool")

    if not work_urls:
        try:
            from backlink_publisher.content.scraper import fetch_work_urls_from_list

            discovered = fetch_work_urls_from_list(
                list_url, main_url=main_url, max_candidates=10,
                insecure_tls=data["insecure_tls"],
            )
            if discovered:
                work_urls = discovered
                fields_derived.append("work_urls")
        except Exception as exc:
            plan_logger.warn(
                "work_urls_discovery_failed",
                main_url=main_url, list_url=list_url,
                reason=type(exc).__name__,
            )

    if fields_derived:
        plan_logger.recon(
            "sites_save_autofilled", main_url=main_url, fields=fields_derived,
        )

    return {
        "main_url": main_url,
        "list_url": list_url,
        "work_urls": work_urls,
        "branded_pool": branded_pool,
        "partial_pool": partial_pool,
        "exact_pool": exact_pool,
        "templates": data["templates"],
        "insecure_tls": data["insecure_tls"],
    }, fields_derived


@bp.route("/sites/save-three-url", methods=["POST"])
def sites_save_three_url() -> Any:
    raw = {
        "main_url": (request.form.get("main_url") or "").strip(),
        "list_url": (request.form.get("list_url") or "").strip(),
        "work_urls": request.form.get("work_urls") or "",
        "branded_pool": request.form.get("branded_pool") or "",
        "partial_pool": request.form.get("partial_pool") or "",
        "exact_pool": request.form.get("exact_pool") or "",
        "work_anchor_templates": request.form.get("work_anchor_templates") or "",
        "count": (request.form.get("count") or "10").strip(),
        "insecure_tls": bool(request.form.get("insecure_tls")),
    }

    validated, errors = _validate_three_url_fields(raw)
    if errors:
        return render_template(
            "sites.html",
            csrf_token=_ensure_csrf_token(),
            form=raw, errors=errors,
            saved="", autofilled=[],
            flash_type="danger",
            flash_msg="请修正下方表单错误",
            default_templates=", ".join(DEFAULT_WORK_TEMPLATES),
            active_page='sites',
        ), 422

    enriched, fields_derived = _derive_three_url_fields(validated)

    entry = ThreeUrlConfig(
        main_url=enriched["main_url"],
        list_url=enriched["list_url"],
        branded_pool=enriched["branded_pool"],
        partial_pool=enriched["partial_pool"],
        exact_pool=enriched["exact_pool"],
        work_urls=enriched["work_urls"],
        work_anchor_templates=enriched["templates"],
        insecure_tls=enriched["insecure_tls"],
    )
    domain_key = enriched["main_url"].rstrip("/")
    cfg = load_config()
    merged = dict(cfg.target_three_url)
    merged[domain_key] = entry
    save_config(cfg, target_anchor_keywords=None, target_three_url=merged)

    redirect_url = f"/sites?saved={domain_key}"
    if fields_derived:
        redirect_url += f"&autofilled={_quote(','.join(fields_derived))}"
    return redirect(redirect_url)


@bp.route("/sites/scrape-preview", methods=["GET"])
def sites_scrape_preview() -> Any:
    url = (request.args.get("url") or "").strip()
    if not url:
        return jsonify({"status": "error", "reason": "missing url param"}), 400
    try:
        meta = fetch_work_metadata(url)
    except InputValidationError as exc:
        return jsonify({"status": "error", "reason": str(exc)}), 200
    except Exception as exc:
        return jsonify({"status": "error", "reason": type(exc).__name__}), 200
    if meta is None:
        return jsonify({"status": "error", "reason": "no metadata extracted"}), 200
    return jsonify({
        "status": "ok",
        "title": meta.title,
        "description": meta.description,
        "h1": meta.h1,
    }), 200


@bp.route("/sites/autopilot", methods=["POST"])
def sites_autopilot() -> Any:
    """Enable or disable autopilot for a site (Plan 2026-06-09-001 U8).

    Body: {site_url: str, enabled: bool, interval_seconds: int}
    Validates interval 3600–2592000. Returns 422 on out-of-range.
    On scheduler failure, rolls back schedule_store and returns 500.
    """
    import webui_store as _ws

    body = request.get_json(silent=True) or {}
    site_url = (body.get("site_url") or "").strip()
    enabled = bool(body.get("enabled", False))
    raw_interval = body.get("interval_seconds", 86400)

    if not site_url:
        return jsonify({"error": "missing site_url"}), 400

    try:
        interval_seconds = int(raw_interval)
    except (TypeError, ValueError):
        return jsonify({"error": "interval_seconds must be an integer"}), 422

    if enabled and not (3600 <= interval_seconds <= 2592000):
        return jsonify({"error": "interval_seconds must be between 3600 (1h) and 2592000 (30d)"}), 422

    _current_targets = _ws.schedule_store.load().get("autopilot_targets", {})
    _site_was_present = site_url in _current_targets
    snapshot_site_cfg = dict(_current_targets[site_url]) if _site_was_present else None

    def _update_fn(settings: Any) -> Any:
        targets = dict(settings.get("autopilot_targets", {}))
        site_cfg = dict(targets.get(site_url, {}))
        site_cfg["enabled"] = enabled
        if enabled:
            site_cfg["interval_seconds"] = interval_seconds
        targets[site_url] = site_cfg
        return {**settings, "autopilot_targets": targets}

    _ws.schedule_store.update(_update_fn)

    next_run_time_iso = None
    try:
        import sys as _sys
        _sched_mod = _sys.modules.get('webui_app.scheduler')
        if enabled:
            assert _sched_mod is not None
            _sched_mod._register_autopilot_job(site_url, interval_seconds)
            if getattr(_sched_mod, '_scheduler', None) is not None:
                try:
                    _job = _sched_mod._scheduler.get_job(_sched_mod._autopilot_job_id(site_url))
                except Exception:
                    _job = None
                if _job is not None and _job.next_run_time is not None:
                    next_run_time_iso = _job.next_run_time.isoformat()
        else:
            try:
                assert _sched_mod is not None
                _sched_mod._scheduler.remove_job(
                    _sched_mod._autopilot_job_id(site_url)
                )
            except Exception:
                pass
    except Exception as exc:
        # Roll back only this site's config; concurrent updates to other sites are preserved.
        def _rollback_fn(s: Any) -> Any:
            targets = dict(s.get("autopilot_targets", {}))
            if _site_was_present:
                targets[site_url] = snapshot_site_cfg
            else:
                targets.pop(site_url, None)
            return {**s, "autopilot_targets": targets}
        _ws.schedule_store.update(_rollback_fn)
        return jsonify({"error": str(exc)}), 500

    # last_run is the prior-cycle timestamp (or None if no cycle has completed yet)
    _updated_cfg = _ws.schedule_store.load().get("autopilot_targets", {}).get(site_url, {})
    return jsonify({
        "ok": True,
        "site_url": site_url,
        "enabled": enabled,
        "next_run_time": next_run_time_iso,
        "last_run": _updated_cfg.get("last_run"),
    }), 200


@bp.route("/sites/run", methods=["POST"])
def sites_run() -> Any:
    return redirect("/ce:keep-alive")


@bp.route("/sites/run/<run_id>/result", methods=["GET"])
def sites_run_result(run_id: str) -> Any:
    return redirect("/ce:keep-alive")


def _plan_gap_summary(path: Any=None) -> dict:
    """Read the latest plan-gap seed JSONL and return a display summary."""
    from datetime import datetime
    import json
    import os
    from pathlib import Path

    path = Path(path) if path is not None else (
        Path(__file__).resolve().parents[2] / "logs" / "plan-gap-latest.json"
    )
    if not path.exists():
        return {"status": "missing"}

    try:
        mtime = os.path.getmtime(path)
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except json.JSONDecodeError:
        return {"status": "invalid", "error": "JSONL 格式損毀"}
    except OSError:
        return {"status": "invalid", "error": "無法讀取 plan-gap 結果"}

    targets = {
        row.get("target_url")
        for row in rows
        if isinstance(row, dict) and row.get("target_url")
    }
    triggered_at = datetime.fromtimestamp(mtime, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    return {
        "status": "ok",
        "candidate_count": len(rows),
        "target_count": len(targets),
        "triggered_at": triggered_at,
    }


def _citation_share_alert() -> dict | None:
    """Return citation share alert info from logs/citation-share-alert.json. Fail-open."""
    import json
    from pathlib import Path

    try:
        path = Path(__file__).resolve().parents[2] / "logs" / "citation-share-alert.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"ts": data.get("ts", "")}
    except Exception:  # noqa: BLE001 — fail-open
        return None
