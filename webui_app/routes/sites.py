"""/sites/* — Plan Unit 3.

R2 (Unit 8): /sites/run and /sites/run/<id>/result are collapsed into
the keep-alive flow — both redirect to /ce:keep-alive.
"""

from __future__ import annotations

from urllib.parse import quote as _quote

from flask import Blueprint, jsonify, redirect, render_template, request

from backlink_publisher.config import (
    DEFAULT_WORK_TEMPLATES,
    ThreeUrlConfig,
    load_config,
    save_config,
)
from backlink_publisher._util.errors import InputValidationError
from backlink_publisher._util.url import validate_https_url, validate_main_domain_url
from backlink_publisher._util.logger import plan_logger
from backlink_publisher.content.scraper import fetch_work_metadata

from ..services.work_themed_service import parse_lines as _parse_lines

from ..helpers._request_cache import _g_cache
from ..helpers.security import _ensure_csrf_token
from ..helpers.url_meta import (
    _derive_branded_pool,
    _derive_exact_pool,
    _derive_partial_pool,
    _verify_urls_or_error,
    fetch_full_tdk,
)

bp = Blueprint("sites", __name__)


@bp.route("/sites", methods=["GET"])
def sites_form():
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

    # all_sites: list of {label, main_url} for the batch-ops table
    all_sites = [
        {"label": label, "main_url": entry.main_url}
        for label, entry in sorted(cfg.target_three_url.items())
    ]

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
    )


@bp.route("/sites/save-three-url", methods=["POST"])
def sites_save_three_url():
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
    errors: dict[str, str] = {}

    main_url = validate_main_domain_url(raw["main_url"])
    if not main_url:
        errors["main_url"] = "必须 https + host-root + 单一尾斜杠（例：https://your-site.com/）"

    list_url: str = ""
    if raw["list_url"]:
        validated = validate_https_url(raw["list_url"])
        if not validated:
            errors["list_url"] = "必须 https"
        else:
            list_url = validated

    work_urls_raw = _parse_lines(raw["work_urls"])
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

    branded_pool = _parse_lines(raw["branded_pool"])
    partial_pool = _parse_lines(raw["partial_pool"])
    exact_pool = _parse_lines(raw["exact_pool"])
    templates = _parse_lines(raw["work_anchor_templates"]) or list(DEFAULT_WORK_TEMPLATES)

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

    # Server-side derivation (plan 006)
    fields_derived: list[str] = []
    tdk: dict | None = None
    if not branded_pool or not partial_pool:
        try:
            tdk = fetch_full_tdk(main_url)
        except Exception as exc:
            plan_logger.warn("tdk_fetch_failed", url=main_url, reason=type(exc).__name__)

    if not list_url:
        list_url = main_url
        fields_derived.append("list_url")
    if not branded_pool:
        branded_pool = _derive_branded_pool(main_url, tdk)
        fields_derived.append("branded_pool")
    if not partial_pool:
        partial_pool = _derive_partial_pool(main_url, tdk)
        fields_derived.append("partial_pool")
    if not exact_pool:
        exact_pool = _derive_exact_pool(main_url)
        fields_derived.append("exact_pool")

    if not work_urls:
        try:
            from backlink_publisher.content.scraper import fetch_work_urls_from_list
            discovered = fetch_work_urls_from_list(
                list_url, main_url=main_url, max_candidates=10,
                insecure_tls=raw["insecure_tls"],
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

    entry = ThreeUrlConfig(
        main_url=main_url, list_url=list_url,
        branded_pool=branded_pool, partial_pool=partial_pool,
        exact_pool=exact_pool, work_urls=work_urls,
        work_anchor_templates=templates,
        insecure_tls=raw["insecure_tls"],
    )
    domain_key = main_url.rstrip("/")
    cfg = load_config()
    merged = dict(cfg.target_three_url)
    merged[domain_key] = entry
    save_config(cfg, target_anchor_keywords=None, target_three_url=merged)

    redirect_url = f"/sites?saved={domain_key}"
    if fields_derived:
        redirect_url += f"&autofilled={_quote(','.join(fields_derived))}"
    return redirect(redirect_url)


@bp.route("/sites/scrape-preview", methods=["GET"])
def sites_scrape_preview():
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


@bp.route("/sites/run", methods=["POST"])
def sites_run():
    return redirect("/ce:keep-alive")


@bp.route("/sites/run/<run_id>/result", methods=["GET"])
def sites_run_result(run_id: str):
    return redirect("/ce:keep-alive")
