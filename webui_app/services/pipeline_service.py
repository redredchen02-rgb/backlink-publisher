"""Flask-free pipeline input assembly — Plan 2026-06-01-001 Unit 2.

Extracted from routes/pipeline.py. Route keeps SSRF gate, session, Flask wiring.
"""
from __future__ import annotations

# detect_language() returns {zh-CN, zh-TW, ja, ko, ru, es, de, fr}.
# SUPPORTED_LANGUAGES = {en, ko, ru, zh-CN} (linkcheck.language).
# Map unsupported codes → nearest supported before they reach the CLI schema gate.
_LANG_NORMALIZE: dict[str, str] = {
    "zh-TW": "zh-CN",
    "ja":    "zh-CN",
    "es":    "en",
    "de":    "en",
    "fr":    "en",
}


def normalize_language(lang: str) -> str:
    """Map a detect_language() result to a SUPPORTED_LANGUAGES member."""
    return _LANG_NORMALIZE.get(lang, lang)


def validate_plan_inputs(main_url: str, category_url: str, work_url: str) -> list[str]:
    """Return https-validation errors for the three-tier URL inputs.

    SSRF enforcement is a separate security gate kept in the route.
    Returns an empty list when all inputs are acceptable.
    """
    errors: list[str] = []
    if not main_url.startswith("https://"):
        errors.append("主网域必须 https")
    if category_url and not category_url.startswith("https://"):
        errors.append("分类页必须 https")
    if work_url and not work_url.startswith("https://"):
        errors.append("漫画页必须 https")
    return errors


def build_plan_config(
    main_url: str,
    url_inputs: list[str],
    target_language: str,
    fetch_tdk: str,
    meta_info: list[dict],
    suggested_anchors: list[str],
) -> dict:
    """Assemble the session config dict for ce:plan."""
    from webui_app.helpers.url_meta import detect_platform, get_main_domain
    return {
        "target_url": main_url,
        "main_domain": get_main_domain(main_url),
        "platform": detect_platform(main_url),
        "url_mode": "C",
        "publish_mode": "publish",
        "target_language": normalize_language(target_language),
        "custom_title": "",
        "custom_tags": "",
        "fetch_tdk": fetch_tdk,
        "suggested_anchors": suggested_anchors,
        "urls": url_inputs,
        "meta_info": meta_info,
    }


def build_generate_seed(
    urls: list[str],
    platform: str,
    url_mode: str,
    publish_mode: str,
    target_language: str,
    custom_title: str,
    custom_tags: str,
    tdk_data: dict,
) -> dict:
    """Assemble the seed dict for ce:generate.

    ``language`` (auto-detected) is normalized so it always falls within
    SUPPORTED_LANGUAGES, preventing CLI schema rejection on .jp/.tw/.es/.de/.fr URLs.
    """
    from webui_app.helpers.url_meta import detect_language, get_main_domain
    main_url = urls[0]
    extra_urls = urls[1:]
    seed: dict = {
        "target_url": main_url,
        "main_domain": get_main_domain(main_url),
        "platform": platform,
        "language": normalize_language(detect_language(main_url)),
        "url_mode": url_mode,
        "publish_mode": publish_mode,
        "target_language": normalize_language(target_language),
    }
    if custom_title:
        seed["custom_title"] = custom_title
    if custom_tags:
        seed["custom_tags"] = custom_tags
    if extra_urls:
        seed["extra_urls"] = extra_urls
    if tdk_data and tdk_data.get("status") == "success":
        suggested = tdk_data.get("suggested_anchors", [])
        if suggested:
            seed["suggested_anchors"] = suggested
    return seed
