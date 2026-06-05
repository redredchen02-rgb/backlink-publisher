"""/batch-campaign — Plan 2026-06-02-001 U4.

Campaign creation page: upload seeds JSONL, select platforms, choose mode
(draft / publish), optionally cap and seed-delay.  Redirects to campaign
progress page (U5) on submit.
"""

from __future__ import annotations

import json

from flask import Blueprint, current_app, redirect, render_template, request, url_for

from backlink_publisher.publishing.registry import registered_platforms

from ..helpers._request_cache import _g_cache
from ..helpers.security import _ensure_csrf_token

bp = Blueprint("batch_campaign", __name__)


def _build_publish_partition():
    """Partition the publishable platforms by connection state for the picker.

    Plan 2026-06-05-007 — shared by the GET form and the POST validation-error
    re-render so the two paths never drift. Mirrors the settings-page data
    source: per-platform offline status + the channel_status lifecycle merged
    through ``partition_channels_by_connection``. Returns ``None`` on any
    failure so the template falls back to the flat list (rendering never 500s).
    """
    try:
        from backlink_publisher.config import load_config
        from backlink_publisher.publishing.registry import active_platforms
        from webui_store import channel_status
        from ..binding_status import get_channel_status
        from ..helpers.channel_tiers import partition_channels_by_connection

        cfg = _g_cache("config", load_config)
        dashboard_channels = [
            (name, get_channel_status(name, cfg)) for name in active_platforms()
        ]
        try:
            statuses = channel_status.list_all()
        except Exception:
            statuses = {}
        return partition_channels_by_connection(dashboard_channels, statuses)
    except Exception:
        return None


@bp.route("/batch-campaign", methods=["GET"])
def batch_campaign_form():
    csrf_token = _ensure_csrf_token()
    platforms = _g_cache("registered_platforms", registered_platforms)
    return render_template(
        "batch_campaign.html",
        csrf_token=csrf_token,
        platforms=sorted(platforms),
        publish_partition=_build_publish_partition(),
        errors={},
        form={},
        active_page="batch_campaign",
    )


@bp.route("/batch-campaign", methods=["POST"])
def batch_campaign_submit():
    csrf_token = _ensure_csrf_token()
    platforms = _g_cache("registered_platforms", registered_platforms)

    seed_text = (request.form.get("seeds", "") or "").strip()
    selected_platforms = request.form.getlist("platforms")
    mode = (request.form.get("mode", "draft") or "").strip()
    cap_raw = (request.form.get("cap") or "").strip()
    seed_delay = (request.form.get("seed_delay", "0") or "").strip()

    errors: dict[str, str] = {}

    # --- Validate seeds ---
    seed_lines = [l.strip() for l in seed_text.split("\n") if l.strip()]
    if not seed_lines:
        errors["seeds"] = "至少输入一条 seed（每行一条 JSON）"
    elif len(seed_lines) > 10:
        errors["seeds"] = f"最多 10 条 seed，当前 {len(seed_lines)} 条"

    parsed_seeds: list[dict] = []
    if "seeds" not in errors:
        for i, line in enumerate(seed_lines):
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    raise ValueError("not a JSON object")
                if "seed_text" not in obj:
                    raise ValueError("missing seed_text field")
                parsed_seeds.append(obj)
            except (json.JSONDecodeError, ValueError) as exc:
                errors.setdefault("seeds", "")
                detail = f"第 {i+1} 行解析失败: {exc}"
                if errors["seeds"]:
                    errors["seeds"] += "; " + detail
                else:
                    errors["seeds"] = detail

    # --- Validate platforms ---
    all_platforms = sorted(platforms)
    valid_platforms = [p for p in selected_platforms if p in all_platforms]
    if not valid_platforms:
        errors["platforms"] = "至少选择一个平台"

    # --- Validate mode ---
    if mode not in ("draft", "publish"):
        errors["mode"] = "模式必须选择 draft 或 publish"

    # --- Validate cap ---
    cap: int | None = None
    if cap_raw:
        try:
            cap = int(cap_raw)
            if cap < 1:
                errors["cap"] = "上限必须 >= 1"
        except (ValueError, TypeError):
            errors["cap"] = "上限必须是正整数"

    # --- Validate seed delay ---
    delay_val: int = 0
    if seed_delay:
        try:
            delay_val = max(0, int(seed_delay))
        except (ValueError, TypeError):
            errors["seed_delay"] = "延迟必须是整数（秒）"

    if errors:
        return render_template(
            "batch_campaign.html",
            csrf_token=csrf_token,
            platforms=all_platforms,
            publish_partition=_build_publish_partition(),
            errors=errors,
            form={
                "seeds": seed_text,
                "platforms": valid_platforms,
                "mode": mode,
                "cap": cap_raw,
                "seed_delay": seed_delay,
            },
            active_page="batch_campaign",
        ), 422

    # --- Create campaign ---
    from webui_store import campaign_store

    campaign_id = campaign_store.create(
        mode=mode,
        platforms=valid_platforms,
        seeds=parsed_seeds,
        cap=cap,
    )

    # Submit to CampaignWorker if it's running.
    worker = current_app.config.get('CAMPAIGN_WORKER')
    if worker is not None:
        worker.start_campaign(campaign_id, {
            "platforms": valid_platforms,
            "mode": mode,
            "cap": cap,
            "seed_delay": seed_delay,
        })

    # Redirect to campaign progress page (U5 — /campaign/<id>).
    return redirect(url_for("campaign_progress.campaign_progress_page",
                            campaign_id=campaign_id))
