"""Shared test helpers for the ``test_config_three_url*.py`` split family.

D1 split (2026-07-02): extracted from ``test_config_three_url.py`` so the
save-config split file (``test_config_three_url_save.py``) doesn't duplicate
these builders. Import:

    from _config_three_url_test_helpers import _write_toml, _basic_three_url
"""
from __future__ import annotations

import os
import stat

from backlink_publisher.config import DEFAULT_WORK_TEMPLATES, ThreeUrlConfig


def _write_toml(tmp_path, body: str):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return path


def _basic_three_url(
    *,
    main_url: str = "https://site.com/",
    list_url: str = "https://site.com/list",
    work_urls: list[str] | None = None,
    branded: list[str] | None = None,
    partial: list[str] | None = None,
    exact: list[str] | None = None,
    work_anchor_templates: list[str] | None = None,
    list_path_blocklist: list[str] | None = None,
    insecure_tls: bool = False,
) -> ThreeUrlConfig:
    return ThreeUrlConfig(
        main_url=main_url,
        list_url=list_url,
        work_urls=work_urls or [],
        branded_pool=branded or ["Site", "Site Hub"],
        partial_pool=partial or ["site hub partial"],
        exact_pool=exact or ["site"],
        work_anchor_templates=(
            work_anchor_templates
            if work_anchor_templates is not None
            else list(DEFAULT_WORK_TEMPLATES)
        ),
        list_path_blocklist=list_path_blocklist,
        insecure_tls=insecure_tls,
    )
