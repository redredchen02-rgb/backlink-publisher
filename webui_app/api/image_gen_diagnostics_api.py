"""ImageGenDiagnosticsAPI — AI-cover (image-gen) connectivity + sample-generation
diagnostics, transport-neutral.

Phase-A facade (Plan 2026-06-18-002 U7, Settings increment). The
``/settings/test-image-gen`` (cheap connectivity probe) and
``/settings/generate-sample-image`` (one real generation call, returned as a
base64 data-URL) logic was **moved here, not copied**, from ``routes/image_gen.py``:
the OpenAI-compatible ``GET /models`` probe, the FRW native ``GET /balance`` probe,
the provider dispatch, and the sample-image generation.

Both the legacy HTML routes and the new ``/api/v1/settings/image-gen/{test-
connection,generate-sample}`` JSON bindings call these and only differ in the
(identical) JSON they render from the neutral :class:`DiagnosticResult`.

Security posture: the endpoints are operator-configured (``config.toml``
``[image_gen]``), NOT user-supplied, so the probes use ``http_client`` with
``allow_private=True`` and there is no SSRF gate here (unlike the LLM diagnostics,
whose endpoint is user-typed). Every outcome is HTTP 200 with an
``{"ok": bool, ...}`` envelope the SPA branches on — a reachability failure is a
successful call reporting a failed probe, not a transport error.

``routes/image_gen.py`` keeps its ``http_client`` import so the lift-parity tests'
``patch("webui_app.routes.image_gen.http_client.get")`` still patches the shared
singleton these probes call. This module performs no transport concerns — it never
touches ``flask.request`` and never aborts.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping

from backlink_publisher._util.errors import ExternalServiceError
from backlink_publisher._util.http_client import http_client
from backlink_publisher._util.logger import plan_logger

from ..helpers._request_cache import _g_cache
from .llm_diagnostics_api import DiagnosticResult


def _probe_openai(base_url: str, api_key: str, model: str) -> dict:
    """Probe OpenAI-compatible gateway via GET /models."""
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = http_client.get(
            f"{base_url}/models",
            headers=headers,
            timeout=10,
            raise_for_status=False,
            allow_private=True,
        )
    except ExternalServiceError as exc:
        return {"ok": False, "error": f"network error: {exc}"}

    if resp.status_code == 401:
        return {"ok": False, "error": "auth_failed: api_key rejected — rotate via `frw-login`"}
    if resp.status_code == 200:
        try:
            payload = resp.json()
            if isinstance(payload, dict) and "data" in payload:
                return {"ok": True, "model_count": len(payload["data"]), "configured_model": model}
        except Exception:
            # debt: image-gen-probe-payload-parse-fallback
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
        resp = http_client.get(
            f"{base_url}/api/frwapi/v1/balance",
            headers=headers,
            timeout=10,
            raise_for_status=False,
            allow_private=True,
        )
    except ExternalServiceError as exc:
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
            # debt: image-gen-probe-payload-parse-fallback
            pass
        return {"ok": True, "configured_model": model}
    return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}


_SAMPLE_PROMPT = (
    "Professional article banner image, clean gradient background, "
    "modern typography style, blue and white color scheme, "
    "wide format 1200x630"
)


class ImageGenDiagnosticsAPI:
    """Stateless facade; instantiate per call (mirrors the other api/*_api facades)."""

    def test_connection(self) -> DiagnosticResult:
        """Probe the configured image-gen endpoint and return connection status.
        Reads ``config.toml`` [image_gen] + the FRW token; never raises (envelope-only).
        """
        try:
            from backlink_publisher._util.secrets import load_frw_token
            from backlink_publisher.config import load_config

            try:
                cfg = _g_cache("config", load_config)
            except Exception as exc:
                # debt: image-gen-test-connection-envelope-catchall
                return DiagnosticResult(
                    {"ok": False, "error": f"load_config failed: {type(exc).__name__}"}
                )

            if cfg.image_gen is None:
                return DiagnosticResult({
                    "ok": False,
                    "error": "no_image_gen_section: add [image_gen] to config.toml first",
                })
            try:
                api_key = load_frw_token()
            except RuntimeError as exc:
                return DiagnosticResult({"ok": False, "error": f"no_token: {type(exc).__name__}"})

            base_url = cfg.image_gen.base_url.rstrip("/")
            model = cfg.image_gen.model
            provider = getattr(cfg.image_gen, "provider", "openai")

            if provider == "frw":
                return DiagnosticResult(_probe_frw(base_url, api_key, model))
            return DiagnosticResult(_probe_openai(base_url, api_key, model))
        except Exception as exc:
            # debt: image-gen-test-connection-envelope-catchall
            plan_logger.warn("image_gen_test_connection_unexpected", reason=type(exc).__name__)
            return DiagnosticResult({"ok": False, "error": f"unexpected: {type(exc).__name__}"})

    def generate_sample(self, fields: Mapping) -> DiagnosticResult:
        """Generate one real test banner and return it as a base64 data-URL.

        Costs one API call. ``fields["prompt"]`` (optional) overrides the default
        banner prompt. Never raises — failures surface as ``{"ok": False, ...}``.
        """
        try:
            from backlink_publisher._util.secrets import load_frw_token
            from backlink_publisher.config import load_config

            try:
                cfg = _g_cache("config", load_config)
            except Exception as exc:
                # debt: image-gen-generate-sample-envelope-catchall
                return DiagnosticResult(
                    {"ok": False, "error": f"load_config failed: {type(exc).__name__}"}
                )

            if cfg.image_gen is None:
                return DiagnosticResult({
                    "ok": False,
                    "error": "no_image_gen_section: add [image_gen] to config.toml first",
                })
            try:
                api_key = load_frw_token()
            except RuntimeError as exc:
                return DiagnosticResult({"ok": False, "error": f"no_token: {type(exc).__name__}"})

            prompt = str(fields.get("prompt") or "").strip() or _SAMPLE_PROMPT

            from backlink_publisher.publishing.adapters.image_gen import ImageGenAdapter

            adapter = ImageGenAdapter(
                base_url=cfg.image_gen.base_url,
                model=cfg.image_gen.model,
                banner_size=cfg.image_gen.banner_size,
                api_key=api_key,
                timeout_s=cfg.image_gen.timeout_s,
                max_retries=cfg.image_gen.max_retries,
                provider=getattr(cfg.image_gen, "provider", "openai"),
                frw_template_id=getattr(cfg.image_gen, "frw_template_id", ""),
            )

            artifact = adapter.generate(prompt)
            b64 = base64.b64encode(artifact.data).decode("ascii")
            data_url = f"data:{artifact.mime};base64,{b64}"

            return DiagnosticResult({
                "ok": True,
                "data_url": data_url,
                "mime": artifact.mime,
                "size_kb": round(len(artifact.data) / 1024, 1),
                "prompt": prompt,
                "source_url": artifact.source_url,
            })
        except Exception as exc:
            # debt: image-gen-generate-sample-envelope-catchall
            plan_logger.warn("image_gen_generate_sample_failed", reason=type(exc).__name__)
            return DiagnosticResult({"ok": False, "error": f"generate failed: {type(exc).__name__}"})
