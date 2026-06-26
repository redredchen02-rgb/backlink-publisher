"""U8a (plan 2026-06-24-001): sdk.plan() / sdk.validate() parity with the CLI.

Tests the *public* backlink_publisher.sdk surface (thin wrappers that accept
list[dict], not raw JSONL) and verify their output matches the CLI subprocess
golden after normalization. Distinct from test_pipeline_inprocess_characterization
which tests the internal PipelineAPI via the webui_app re-export shim.

Coverage:
  G1  sdk.plan(dict)  succeeds → rows match CLI normalized output
  G2  sdk.validate(list[dict]) succeeds → rows match CLI normalized output
  G3  sdk.validate(malformed) → success=False, exit_code=2 (InputValidationError)
  G4  sdk.validate() stdout does NOT contain the config-echo diagnostic banner
"""

from __future__ import annotations

__tier__ = "unit"

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import backlink_publisher.sdk as sdk

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DIR = _REPO_ROOT / "src"
_MODULES = {
    "validate-backlinks": "backlink_publisher.cli.validate_backlinks",
    "plan-backlinks": "backlink_publisher.cli.plan_backlinks",
}


# ── input fixtures ────────────────────────────────────────────────────────────

def _valid_plan_seed() -> dict:
    return {
        "target_url": "https://example.com/article",
        "main_domain": "https://example.com",
        "language": "en",
        "platform": "medium",
        "url_mode": "A",
        "publish_mode": "draft",
        "topic": "Test Topic",
    }


def _valid_validate_payload() -> dict:
    return {
        "id": "abc123",
        "platform": "medium",
        "language": "en",
        "publish_mode": "draft",
        "target_url": "https://example.com/article",
        "main_domain": "https://example.com",
        "url_mode": "A",
        "title": "Test Article",
        "slug": "test-article",
        "excerpt": "A test excerpt.",
        "tags": ["tag1", "tag2"],
        "content_markdown": (
            "This is a test article about https://example.com and some content here."
        ),
        "links": [
            {"url": "https://example.com", "anchor": "Example",
             "kind": "main_domain", "required": True},
            {"url": "https://example.com/article", "anchor": "Article",
             "kind": "target", "required": True},
            {"url": "https://wikipedia.org", "anchor": "Wiki",
             "kind": "supporting", "required": False},
            {"url": "https://mdn.dev", "anchor": "MDN",
             "kind": "supporting", "required": False},
            {"url": "https://stackoverflow.com", "anchor": "SO",
             "kind": "supporting", "required": False},
            {"url": "https://github.com", "anchor": "GitHub",
             "kind": "supporting", "required": False},
        ],
        "seo": {
            "title": "Test Article | SEO",
            "description": "SEO description",
            "canonical_url": "https://example.com/article",
        },
    }


# ── CLI subprocess runner ─────────────────────────────────────────────────────

@pytest.fixture
def cfg_dir(tmp_path) -> str:
    d = tmp_path / "cfg"
    d.mkdir()
    return str(d)


def _run_cli(module_key: str, argv: list[str], stdin: str, cfg_dir: str, **extra_env: str) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_SRC_DIR) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    env["PYTHONHASHSEED"] = "0"
    env["BACKLINK_PUBLISHER_CONFIG_DIR"] = cfg_dir
    env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, "-m", _MODULES[module_key], *argv],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        env=env,
    )
    rows = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip()]
    return {"rows": rows, "returncode": proc.returncode, "stderr": proc.stderr}


# ── normalization helpers ─────────────────────────────────────────────────────

def _normalize_plan(rows: list[dict]) -> list[dict]:
    """Drop run-variant fields: run_id, *_at timestamps."""
    out = []
    for row in rows:
        row = json.loads(json.dumps(row))
        row.pop("run_id", None)
        for k in list(row):
            if k.endswith("_at"):
                row.pop(k)
        out.append(row)
    return out


def _normalize_validate(rows: list[dict]) -> list[dict]:
    """Drop validation.checked_at which varies per run."""
    out = []
    for row in rows:
        row = json.loads(json.dumps(row))
        if isinstance(row.get("validation"), dict):
            row["validation"].pop("checked_at", None)
        out.append(row)
    return out


# ── G1: sdk.plan parity ───────────────────────────────────────────────────────

def test_sdk_plan_matches_cli_subprocess(cfg_dir):
    """G1: sdk.plan(dict) produces same normalized rows as plan-backlinks CLI."""
    seed = _valid_plan_seed()
    stdin = json.dumps(seed) + "\n"

    cli = _run_cli(
        "plan-backlinks", ["--no-fetch-verify"],
        stdin=stdin, cfg_dir=cfg_dir,
        BACKLINK_NO_FETCH_VERIFY="1",
    )
    assert cli["returncode"] == 0, f"CLI plan failed: {cli['stderr']}"

    res = sdk.plan(seed)
    assert res.success is True, f"sdk.plan failed: {res.error}"
    assert res.exit_code == 0

    assert _normalize_plan(res.rows) == _normalize_plan(cli["rows"]), (
        f"SDK rows differ from CLI rows after normalization.\n"
        f"SDK:  {res.rows}\n"
        f"CLI:  {cli['rows']}"
    )


# ── G2: sdk.validate parity ───────────────────────────────────────────────────

def test_sdk_validate_matches_cli_subprocess(cfg_dir):
    """G2: sdk.validate(list[dict]) produces same normalized rows as CLI."""
    payload = _valid_validate_payload()
    stdin = json.dumps(payload) + "\n"

    cli = _run_cli(
        "validate-backlinks", ["--no-validate-url-check"],
        stdin=stdin, cfg_dir=cfg_dir,
    )
    assert cli["returncode"] == 0, f"CLI validate failed: {cli['stderr']}"

    res = sdk.validate([payload], no_check_urls=True)
    assert res.success is True, f"sdk.validate failed: {res.error}"
    assert res.exit_code == 0

    assert _normalize_validate(res.rows) == _normalize_validate(cli["rows"]), (
        f"SDK rows differ from CLI rows after normalization.\n"
        f"SDK:  {res.rows}\n"
        f"CLI:  {cli['rows']}"
    )


# ── G3: error path ────────────────────────────────────────────────────────────

def test_sdk_validate_malformed_exits_2():
    """G3: sdk.validate(malformed) → success=False, exit_code=2, InputValidationError."""
    bad = {"id": "x", "platform": "unsupported_xyz"}
    res = sdk.validate([bad], no_check_urls=True)
    assert res.success is False
    assert res.exit_code == 2
    assert res.error_class == "InputValidationError"


# ── G4: no config_echo banner in SDK stdout ───────────────────────────────────

def test_sdk_validate_stdout_contains_no_banner():
    """G4: config-echo diagnostic banner appears only in CLI stderr, not SDK stdout."""
    payload = _valid_validate_payload()
    res = sdk.validate([payload], no_check_urls=True)
    assert res.success is True

    # The banner marker is "Config:" or the line starting with "===" (config-echo format)
    for line in res.stdout.splitlines():
        assert not line.startswith("Config:"), (
            f"config-echo banner leaked into SDK stdout: {line!r}"
        )
        assert not line.startswith("BACKLINK_"), (
            f"env dump leaked into SDK stdout: {line!r}"
        )
