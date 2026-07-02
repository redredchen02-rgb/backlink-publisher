"""LlmDiagnosticsAPI — LLM connection + generation diagnostics, transport-neutral.

Phase-A facade (Plan 2026-06-18-002 U7, Settings increment). The
``/settings/test-llm-connection`` and ``/settings/test-llm-generation`` logic was
**moved here, not copied**, from ``routes/llm.py``: the SSRF-guarded connection
probe (guard → GET /models → /chat/completions fallback, with the best-effort
"last test" persistence), the bounded redirect-rejecting ``_safe_get_json``, and
the article/anchor generation preview.

Both the legacy HTML routes and the new ``/api/v1/settings/llm/{test-connection,
test-generation}`` JSON bindings call these and only differ in the (identical)
JSON they render from the neutral :class:`DiagnosticResult`.

Security: the endpoint URL is SSRF-guarded (``_guard_llm_endpoint``) BEFORE the
api_key is sent, and ``_safe_get_json`` refuses redirects (a 3xx would re-issue
the Bearer header against an attacker-chosen target — ce:review C1 / sec-001).
``_guard_llm_endpoint`` / ``_safe_post_json`` are the canonical
``backlink_publisher.llm.http_guard`` helpers; ``routes/llm.py`` re-exports them
(and ``_safe_get_json``) for the lift-parity + SSRF tests. This module performs no
transport concerns — it never touches ``flask.request`` and never aborts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Any

import requests

from backlink_publisher._util.logger import plan_logger
from backlink_publisher.llm.http_guard import (
    guard_llm_endpoint as _guard_llm_endpoint,
)
from backlink_publisher.llm.http_guard import (
    LLM_MAX_RESPONSE_BYTES as _LLM_TEST_MAX_BYTES,
)
from backlink_publisher.llm.http_guard import (
    safe_post_json as _safe_post_json,
)

from ..helpers.contexts import _load_llm_settings


@dataclass(frozen=True)
class DiagnosticResult:
    """Transport-neutral diagnostic outcome: the JSON body + its HTTP status.
    Both transports render ``jsonify(payload), http_status`` identically."""

    payload: dict
    http_status: int = 200


def _safe_get_json(url: str, headers: dict, timeout: int = 10) -> Any:
    """Bounded GET with content-type + size guards. Returns ``(status, json)`` or
    raises ValueError.

    ``allow_redirects=False`` (ce:review C1 / sec-001): the SSRF gate is one-shot
    at input. Following redirects would re-issue the request (including the Bearer
    api_key header) against an attacker-chosen target, defeating the gate.
    """
    resp = requests.get(url, headers=headers, timeout=timeout, stream=True,
                        allow_redirects=False)
    if 300 <= resp.status_code < 400:
        raise ValueError(
            f"redirect_not_allowed: upstream returned {resp.status_code}; "
            f"refusing to follow Location header")
    ctype = resp.headers.get("Content-Type", "")
    if "json" not in ctype.lower():
        raise ValueError(f"bad_content_type: {ctype!r}")
    body = b""
    for chunk in resp.iter_content(chunk_size=8192):
        body += chunk
        if len(body) > _LLM_TEST_MAX_BYTES:
            raise ValueError(
                f"response_too_large: exceeded {_LLM_TEST_MAX_BYTES} bytes")
    return resp.status_code, json.loads(body)


def _s(fields: Mapping, name: str) -> str:
    return str(fields.get(name) or "").strip()


class LlmDiagnosticsAPI:
    """Stateless facade; instantiate per call (mirrors the other api/*_api facades)."""

    def test_connection(self, fields: Mapping) -> DiagnosticResult:
        """Run the connection probe, then persist the outcome (best-effort) so the
        nav pill / status header reflect last-known health across reloads."""
        payload, status = self._run_connection(fields)
        st = payload.get("status")
        if st in ("ok", "failed", "error"):
            try:
                from ..services import settings_service
                settings_service.record_llm_test_result(
                    ok=(st == "ok"), message=payload.get("message", ""))
            except Exception as e:
                # Best-effort persistence — never break the test response. Log so a
                # recurring write failure (disk full, perms) is diagnosable.
                plan_logger.warn("failed to persist llm test result", error=str(e))
        return DiagnosticResult(payload, status)

    def _run_connection(self, fields: Mapping) -> tuple[dict, int]:
        try:
            endpoint = _s(fields, "endpoint").rstrip("/")
            api_key = _s(fields, "api_key")
            model = _s(fields, "model")

            # P3 fallback: form sends blanks when secrets aren't re-typed; read stored.
            if not api_key or not endpoint:
                stored = _load_llm_settings()
                api_key = api_key or stored.get("api_key", "")
                endpoint = endpoint or stored.get("endpoint", "").rstrip("/")
                model = model or stored.get("model", "")

            if not endpoint or not api_key:
                return {"status": "error", "message": "请填写 Endpoint 和 API Key"}, 200

            # Guard endpoint URL BEFORE sending the api_key. SSRF gate + host
            # allowlist + scheme check.
            reason, detail = _guard_llm_endpoint(f"{endpoint}/models")
            if reason is not None:
                return {
                    "status": "failed",
                    "reason": reason,
                    "message": f"endpoint URL rejected ({reason}): {detail}",
                }, 400

            test_url = f"{endpoint}/models"
            headers = {"Authorization": f"Bearer {api_key}"}

            models_list = []
            try:
                status, m_data = _safe_get_json(test_url, headers)
                if status == 200:
                    if isinstance(m_data, dict) and "data" in m_data:
                        models_list = [m["id"] for m in m_data["data"]
                                       if isinstance(m, dict) and "id" in m]
                    return {"status": "ok", "message": "连接成功！", "models": models_list}, 200

                # Fallback to /chat/completions with the same guards.
                fb_url = f"{endpoint}/chat/completions"
                reason, detail = _guard_llm_endpoint(fb_url)
                if reason is not None:
                    return {
                        "status": "failed",
                        "reason": reason,
                        "message": f"endpoint URL rejected ({reason}): {detail}",
                    }, 400
                data = {
                    "model": model or "gpt-3.5-turbo",
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                }
                status, _ = _safe_post_json(fb_url, headers, data)
                if status == 200:
                    return {"status": "ok", "message": "连接成功！", "models": []}, 200

                return {"status": "error", "message": f"连接失败: HTTP {status}"}, 200
            except ValueError as ve:
                # Raised by _safe_get_json/_safe_post_json for size/content-type
                # violations. Surface the structured reason but don't expose raw bytes.
                return {
                    "status": "failed",
                    "reason": "response_invalid",
                    "message": f"响应不合规: {ve}",
                }, 400
            except Exception as e:
                # debt: llm-diagnostics-run-connection-error-envelope
                plan_logger.warn("llm_test_connection_request_error", error=type(e).__name__)
                return {"status": "error", "message": f"请求异常: {type(e).__name__}"}, 200
        except Exception as e:
            # debt: llm-diagnostics-run-connection-error-envelope
            plan_logger.warn("llm_test_connection_unexpected_error", error=type(e).__name__)
            return {"status": "error", "message": f"发生错误: {type(e).__name__}"}, 200

    def test_generation(self, fields: Mapping) -> DiagnosticResult:
        try:
            from backlink_publisher.publishing.adapters.llm_anchor_provider import (
                OpenAICompatibleProvider,
            )
            settings = _load_llm_settings()

            provider = OpenAICompatibleProvider(
                base_url=settings["endpoint"],
                api_key=settings["api_key"],
                model=settings["model"],
                temperature=settings["temperature"],
                system_prompt=settings["system_prompt"],
                article_system_prompt=settings["article_system_prompt"],
            )

            test_title = fields.get("test_title", "测试文章")

            if settings.get("use_article_gen"):
                result = provider.generate_article_body(
                    domain_label="51acgs.com",
                    main_domain="https://51acgs.com",
                    anchors=["示例锚点", "更多资源"],
                    topic=test_title,
                )
                return DiagnosticResult({"status": "ok", "result": result}, 200)
            from backlink_publisher.publishing.adapters.llm_anchor_provider import (
                LLMAnchorRequest,
            )
            req = LLMAnchorRequest(keyword=test_title, domain="51acgs.com",
                                   target_url="https://51acgs.com")
            result = provider.generate_candidates(req)
            return DiagnosticResult(
                {"status": "ok", "result": f"生成的锚点候选: {', '.join(result)}"}, 200)
        except Exception as e:
            # debt: llm-diagnostics-test-generation-error-envelope
            plan_logger.warn("llm_test_generation_failed", reason=type(e).__name__)
            return DiagnosticResult(
                {"status": "error", "message": f"生成预览失败: {type(e).__name__}"}, 200
            )
