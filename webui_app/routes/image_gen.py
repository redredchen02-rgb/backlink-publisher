"""Image-gen settings routes — Plan 2026-05-20-001 Unit 6.

Provides ``/settings/test-image-gen`` so the operator can verify
that the configured base_url + frw-token are reachable BEFORE
running plan-backlinks (which would otherwise discover a broken
key only after burning quota on retries).

Provider dispatch:
  * ``provider="openai"`` (default) — ``GET <base_url>/models`` probe
    (cheapest OpenAI-compatible endpoint that doesn't bill for generation).
  * ``provider="frw"`` — ``GET <base_url>/api/frwapi/v1/balance`` probe
    using ``X-Api-Key`` header (FRW native API, returns credit balance).
"""

from __future__ import annotations

from flask import Blueprint, jsonify

import requests

from ..helpers._request_cache import _g_cache

bp = Blueprint("image_gen", __name__)


def _probe_openai(base_url: str, api_key: str, model: str) -> dict:
    """Probe OpenAI-compatible gateway via GET /models."""
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.get(f"{base_url}/models", headers=headers, timeout=10)
    except requests.RequestException as exc:
        return {"ok": False, "error": f"network error: {exc}"}

    if resp.status_code == 401:
        return {"ok": False, "error": "auth_failed: api_key rejected — rotate via `frw-login`"}
    if resp.status_code == 200:
        try:
            payload = resp.json()
            if isinstance(payload, dict) and "data" in payload:
                return {"ok": True, "model_count": len(payload["data"]), "configured_model": model}
        except Exception:
            pass
        return {"ok": True, "model_count": 0, "configured_model": model}
    if resp.status_code == 404:
        # Gateway reachable but doesn't expose /models (common with private
        # OpenAI-compatible proxies). Report ok — auth is implicitly valid
        # since a real 401 would have been returned instead.
        return {"ok": True, "configured_model": model, "note": "endpoint reachable (no /models)"}
    return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}


def _probe_frw(base_url: str, api_key: str, model: str) -> dict:
    """Probe FRW native API via GET /api/frwapi/v1/balance (X-Api-Key auth)."""
    headers = {"X-Api-Key": api_key}
    try:
        resp = requests.get(
            f"{base_url}/api/frwapi/v1/balance", headers=headers, timeout=10
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": f"network error: {exc}"}

    if resp.status_code == 401:
        return {"ok": False, "error": "auth_failed: api_key rejected — rotate via `frw-login`"}
    if resp.status_code == 403:
        return {"ok": False, "error": "forbidden: key disabled, expired, or IP not whitelisted"}
    if resp.status_code == 200:
        try:
            payload = resp.json()
            data = payload.get("data") or {}
            credits = data.get("creditsRemaining")
            return {
                "ok": True,
                "configured_model": model,
                "frw_credits_remaining": credits,
            }
        except Exception:
            pass
        return {"ok": True, "configured_model": model}
    return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}


@bp.route("/settings/test-image-gen", methods=["POST"])
def settings_test_image_gen():
    """Probe the configured image-gen endpoint and return connection status."""
    try:
        from backlink_publisher.config import load_config
        from backlink_publisher._util.secrets import load_frw_token

        try:
            cfg = _g_cache('config', load_config)
        except Exception as exc:
            return jsonify({"ok": False, "error": f"load_config failed: {exc}"}), 200

        if cfg.image_gen is None:
            return jsonify({
                "ok": False,
                "error": "no_image_gen_section: add [image_gen] to config.toml first",
            }), 200

        try:
            api_key = load_frw_token()
        except RuntimeError as exc:
            return jsonify({"ok": False, "error": f"no_token: {exc}"}), 200

        base_url = cfg.image_gen.base_url.rstrip("/")
        model = cfg.image_gen.model
        provider = getattr(cfg.image_gen, "provider", "openai")

        if provider == "frw":
            result = _probe_frw(base_url, api_key, model)
        else:
            result = _probe_openai(base_url, api_key, model)

        return jsonify(result), 200
    except Exception as exc:
        return jsonify({"ok": False, "error": f"unexpected: {exc}"}), 200
