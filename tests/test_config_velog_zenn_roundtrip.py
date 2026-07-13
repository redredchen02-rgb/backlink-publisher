"""Regression: [velog]/[zenn] config sections must survive save_config round-trips.

Finding [00] (2026-07-13 audit): ``velog`` (dofollow=True) and ``zenn`` are
registered non-retired platforms, so they land in ``_save_config_known_roots()``,
but ``save_config`` emitted no ``[velog]``/``[zenn]`` block — so
``_preserve_unknown_sections`` classified their root-only headings as
managed+sub=None and DROPPED them on every write once the adapter registry was
populated (the WebUI steady state). The result was silent, permanent config data
loss on a documented operator config path (see ``zenn_github.py`` /
``publishing/adapters/_setup_checks.py`` error messages that instruct operators to
hand-add ``[zenn]``).

Same bug *class* as the 2026-05-14 config-save data-loss incident, see
``docs/solutions/test-failures/inverted-negative-assertion-enshrined-config-save-data-loss-2026-05-14.md``.
Positive-shape assertions per R9; value-level round-trip (reload + compare the
Config object) rather than file-byte presence, so a regression that keeps the
heading but mangles the values still fails.
"""
from __future__ import annotations

__tier__ = "unit"

from pathlib import Path

# Populate the adapter registry so velog/zenn are non-retired registered
# platforms in _save_config_known_roots() — this is the precondition under
# which the drop bites (the long-running WebUI has the registry populated).
import backlink_publisher.publishing.adapters  # noqa: F401  (register() side effects)
from backlink_publisher.config import load_config, save_config


def test_velog_and_zenn_survive_unrelated_save(tmp_path: Path) -> None:
    """An unrelated save (adding a blogger blog id) must not wipe [velog]/[zenn]."""
    src = tmp_path / "config.toml"
    cookies_file = tmp_path / "custom-velog-cookies.json"
    toml_cookies = str(cookies_file).replace("\\", "\\\\")  # TOML-escape backslashes
    src.write_text(
        "[blogger]\n"
        '"https://example.com" = "111"\n'
        "\n"
        "[velog]\n"
        f'cookies_path = "{toml_cookies}"\n'
        "\n"
        "[zenn]\n"
        'github_repo = "me/zenn-content"\n'
        'username = "me"\n'
        'branch = "main"\n',
        encoding="utf-8",
    )

    cfg = load_config(src)
    # Loader-fixture preconditions: the TOML sections populated the Config.
    assert cfg.velog is not None, "fixture: loader must populate Config.velog"
    assert cfg.velog.cookies_path == cookies_file
    assert cfg.zenn is not None, "fixture: loader must populate Config.zenn"
    assert cfg.zenn.github_repo == "me/zenn-content"
    assert cfg.zenn.username == "me"

    # Unrelated write — exactly the flow that silently wiped the sections.
    save_config(cfg, path=src, extra_blogger_ids={"https://other.com": "222"})

    cfg_after = load_config(src)
    assert cfg_after.velog is not None, "[velog] section dropped by save_config"
    assert cfg_after.velog.cookies_path == cfg.velog.cookies_path
    assert cfg_after.zenn is not None, "[zenn] section dropped by save_config"
    assert cfg_after.zenn == cfg.zenn


def test_velog_zenn_survive_default_roundtrip(tmp_path: Path) -> None:
    """A plain load-then-save round-trip (no overrides) also preserves both sections."""
    src = tmp_path / "config.toml"
    src.write_text(
        "[blogger]\n"
        '"https://example.com" = "111"\n'
        "\n"
        "[velog]\n"
        "\n"
        "[zenn]\n"
        'github_repo = "acct/zenn"\n'
        'username = "acct"\n',
        encoding="utf-8",
    )

    cfg = load_config(src)
    assert cfg.velog is not None and cfg.zenn is not None, "fixture precondition"

    save_config(cfg, path=src)

    cfg_after = load_config(src)
    assert cfg_after.velog is not None, "[velog] dropped on plain round-trip"
    assert cfg_after.zenn is not None, "[zenn] dropped on plain round-trip"
    assert cfg_after.zenn.github_repo == "acct/zenn"
    assert cfg_after.zenn.username == "acct"
