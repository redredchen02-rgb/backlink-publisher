"""LlmSettingsAPI — LLM / image-gen settings save, transport-neutral.

Phase-A facade (Plan 2026-06-18-002 U7, Settings increment). The
``/settings/save-llm-config`` logic was **moved here, not copied**, from
``routes/llm.py``: the clear-to-defaults path, the https endpoint gates, the
blank-secret-preserves rule, the AI-cover (image-gen) validation, the ``0600``
``llm-settings.json`` write (``api_key`` is a long-term secret), and the bridge
that syncs the Pro-Mode image settings into the real pipeline ``Config.image_gen``.

Both the legacy ``/settings/save-llm-config`` HTML route and the new
``/api/v1/settings/llm-config`` JSON binding call ``save`` and only differ in how
they render the neutral :class:`LlmSaveResult`.

Scope: the save route only. The two diagnostic routes (``test-llm-connection`` /
``test-llm-generation``) already return JSON and carry heavy SSRF-internal test
patching on ``routes.llm.*``; they migrate in a later increment.

This module performs no transport concerns — it never touches ``flask.request``
and never aborts. ``save`` takes a ``fields`` mapping (``request.form`` for the
legacy route, the parsed JSON body for ``/api/v1``); ``_truthy_flag`` bridges the
checkbox semantics gap (form = key-presence means checked; JSON = a real bool).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json

from backlink_publisher._util.logger import plan_logger
from backlink_publisher.persistence.safe_write import atomic_write

from ..helpers.contexts import _llm_settings_file, _load_llm_settings

_LLM_DEFAULTS = {
    "api_key": "",
    "endpoint": "",
    "model": "",
    "temperature": 0.7,
    "system_prompt": "",
    "use_article_gen": False,
    "article_system_prompt": "",
    "image_gen_api_key": "",
    "image_gen_endpoint": "",
    "image_gen_model": "",
    "image_gen_banner_size": "1200x630",
    "use_image_gen": False,
}

_AI_FRAGMENT = "sect-ai"


@dataclass(frozen=True)
class LlmSaveResult:
    """Transport-neutral outcome of an LLM settings save/clear.

    ``level`` drives the legacy flash type (success / danger). ``error_class`` is
    set only on failure and selects the ``/api/v1`` status: ``invalid_request`` →
    422, ``persistence_failure`` → 502.
    """

    level: str
    message: str
    fragment: str = _AI_FRAGMENT
    error_class: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_class is None


def _s(fields: Mapping, name: str) -> str:
    """Stripped string read, tolerant of non-string JSON values."""
    return str(fields.get(name) or "").strip()


def _truthy_flag(fields: Mapping, name: str) -> bool:
    """Checkbox semantics across transports: a form sends the key only when
    checked (value 'on'); JSON sends a real bool. Absent → False; bool → itself;
    present-as-string → True (form-checked)."""
    if name not in fields:
        return False
    v = fields[name]
    if isinstance(v, bool):
        return v
    return True


def _write_llm_settings(payload: dict) -> None:
    # Delegates to the canonical credential-write helper so the file lands 0o600
    # (api_key is a long-term secret). PR #139 hand-rolled this write and forgot
    # the chmod, leaving llm-settings.json world-readable.
    path = _llm_settings_file()
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    atomic_write(path, text)


def _sync_image_gen_config(*, enabled: bool, endpoint: str, model: str,
                           banner_size: str, api_key: str) -> None:
    """Bridge the WebUI Pro Mode image settings into the real pipeline config.

    The plan/publish pipeline does NOT read ``llm-settings.json`` for banners: it
    reads ``Config.image_gen`` plus ``frw-token.json``. Keeping this bridge in the
    save path makes the Settings UI's "AI 封面生成" switch mean what it says
    without moving long-term secrets into TOML.
    """
    from backlink_publisher._util.secrets import write_frw_token
    from backlink_publisher.config import ImageGenConfig, load_config, save_config

    if api_key:
        write_frw_token(api_key)

    cfg = load_config()
    existing = cfg.image_gen

    if not enabled:
        if existing is not None:
            save_config(
                cfg,
                image_gen_config=ImageGenConfig(
                    base_url=existing.base_url,
                    model=existing.model,
                    banner_size=existing.banner_size,
                    daily_cap=existing.daily_cap,
                    per_run_cap=existing.per_run_cap,
                    timeout_s=existing.timeout_s,
                    max_retries=existing.max_retries,
                    strict=existing.strict,
                    auto_disable_threshold=existing.auto_disable_threshold,
                    use_image_gen=False,
                ),
            )
        return

    save_config(
        cfg,
        image_gen_config=ImageGenConfig(
            base_url=endpoint,
            model=model,
            banner_size=banner_size or (existing.banner_size if existing else "1200x630"),
            daily_cap=existing.daily_cap if existing else 50,
            per_run_cap=existing.per_run_cap if existing else 10,
            timeout_s=existing.timeout_s if existing else 30.0,
            max_retries=existing.max_retries if existing else 3,
            strict=existing.strict if existing else False,
            auto_disable_threshold=existing.auto_disable_threshold if existing else 5,
            use_image_gen=True,
        ),
    )


class LlmSettingsAPI:
    """Stateless facade; instantiate per call (mirrors the other api/*_api facades)."""

    def get_config(self) -> dict:
        """Redaction-safe LLM/image-gen settings for the SPA form to hydrate.

        SECURITY (PR #139 P3): the two secrets — ``api_key`` and
        ``image_gen_api_key`` — are NEVER returned; only ``has_*`` booleans are, so
        the form shows a "已设置 (留空保留现值)" placeholder and a blank submit
        preserves the stored secret (the save path's blank-secret-preserve rule).
        """
        s = _load_llm_settings()
        return {
            "endpoint": s.get("endpoint", ""),
            "model": s.get("model", ""),
            "temperature": s.get("temperature", 0.7),
            "system_prompt": s.get("system_prompt", ""),
            "article_system_prompt": s.get("article_system_prompt", ""),
            "use_article_gen": bool(s.get("use_article_gen")),
            "use_image_gen": bool(s.get("use_image_gen")),
            "image_gen_endpoint": s.get("image_gen_endpoint", ""),
            "image_gen_model": s.get("image_gen_model", ""),
            "image_gen_banner_size": s.get("image_gen_banner_size", "1200x630"),
            "has_api_key": bool(s.get("api_key")),
            "has_image_gen_api_key": bool(s.get("image_gen_api_key")),
        }

    def save(self, fields: Mapping) -> LlmSaveResult:
        if fields.get("action") == "clear":
            try:
                _write_llm_settings(dict(_LLM_DEFAULTS))
                return LlmSaveResult("success", "LLM 配置已清除")
            except Exception as e:
                plan_logger.error("llm_settings_clear_failed", error=str(e))
                return LlmSaveResult(
                    "danger", f"清除失败: {type(e).__name__}", error_class="persistence_failure"
                )

        existing = _load_llm_settings()
        try:
            temperature = float(fields.get("temperature", existing.get("temperature", 0.7)))
        except (ValueError, TypeError):
            temperature = existing.get("temperature", 0.7)

        # P3: blank secret inputs preserve the stored value so partial edits don't wipe it.
        new_api_key = _s(fields, "api_key")
        new_image_key = _s(fields, "image_gen_api_key")

        # Reject a non-empty non-https endpoint up front — the pipeline bridge
        # requires https, so an http endpoint would leave Pro Mode silently
        # inactive at publish time. A blank endpoint is a partial edit, not a
        # violation, so it passes through unchanged.
        new_endpoint = _s(fields, "endpoint").rstrip("/")
        if new_endpoint and not new_endpoint.startswith("https://"):
            return LlmSaveResult("danger", "Endpoint 必须以 https:// 开头", error_class="invalid_request")

        use_image_gen = _truthy_flag(fields, "use_image_gen")
        image_endpoint = (
            _s(fields, "image_gen_endpoint").rstrip("/")
            or existing.get("image_gen_endpoint", "").strip().rstrip("/")
            or new_endpoint
        )
        image_model = (
            _s(fields, "image_gen_model")
            or existing.get("image_gen_model", "").strip()
            or _s(fields, "model")
        )
        image_banner_size = (
            _s(fields, "image_gen_banner_size")
            or existing.get("image_gen_banner_size", "1200x630")
            or "1200x630"
        )
        if use_image_gen:
            if not image_endpoint or not image_model:
                return LlmSaveResult(
                    "danger", "启用 AI 封面生成时必须填写 Image Endpoint 和 Image Model",
                    error_class="invalid_request",
                )
            if not image_endpoint.startswith("https://"):
                return LlmSaveResult("danger", "Image Endpoint 必须以 https:// 开头",
                                     error_class="invalid_request")

        existing.update({
            "endpoint": new_endpoint,
            "api_key": new_api_key or existing.get("api_key", ""),
            "model": _s(fields, "model") or existing.get("model", ""),
            "temperature": temperature,
            "system_prompt": str(fields.get("system_prompt") or "") or existing.get("system_prompt", ""),
            "use_article_gen": _truthy_flag(fields, "use_article_gen"),
            "article_system_prompt": str(fields.get("article_system_prompt") or ""),
            "image_gen_api_key": new_image_key or existing.get("image_gen_api_key", ""),
            "image_gen_endpoint": image_endpoint,
            "image_gen_model": image_model,
            "image_gen_banner_size": image_banner_size,
            "use_image_gen": use_image_gen,
        })
        try:
            _write_llm_settings(existing)
            _sync_image_gen_config(
                enabled=use_image_gen,
                endpoint=image_endpoint,
                model=image_model,
                banner_size=image_banner_size,
                api_key=new_image_key,
            )
            return LlmSaveResult("success", "LLM 设定已保存")
        except Exception as e:
            plan_logger.error("llm_settings_save_failed", error=str(e))
            return LlmSaveResult(
                "danger", f"保存失败: {type(e).__name__}", error_class="persistence_failure"
            )
