"""WebUI route contract tests — core routes."""

from __future__ import annotations

__tier__ = "integration"

import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── _no_real_subprocess: belt-and-suspenders backup for _no_run_pipe ─────────

@pytest.fixture(autouse=True)
def _no_real_subprocess():
    """Stub subprocess.run so routes never shell out to real CLI binaries."""
    import subprocess as sp_mod

    def _fake_run(cmd, *_args, **_kwargs):
        result = sp_mod.CompletedProcess(args=cmd, returncode=0)
        result.stdout = ""
        result.stderr = ""
        return result

    with patch("subprocess.run", side_effect=_fake_run):
        yield

# ── _no_run_pipe: stub run_pipe so routes don't shell out ─────────────────────

@pytest.fixture(autouse=True)
def _no_run_pipe():
    """Stub run_pipe in every webui consumer module so routes don't shell out."""

    def _fake(_cmd, _stdin):
        return {"stdout": "", "stderr": ""}

    def _fake_capture(_cmd, _stdin):
        return {"stdout": "", "stderr": "", "returncode": 0}

    targets = [
        ("backlink_publisher.sdk._cli_runner.run_pipe", _fake),
        ("backlink_publisher.sdk.api.run_pipe", _fake),
        ("backlink_publisher.sdk.api.run_pipe_capture", _fake_capture),
    ]
    patches = [patch(t, side_effect=f) for t, f in targets]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


# ── _isolated_webui_state: redirect store singletons to per-test tmp ─────────

@pytest.fixture(autouse=True)
def _isolated_webui_state(tmp_path, monkeypatch):
    """Redirect webui_store singleton paths to a per-test tmp dir."""
    import webui_store as _ws

    state_dir = tmp_path / "webui_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_ws.history_store, "path", state_dir / "publish-history.json")
    monkeypatch.setattr(_ws.profiles_store, "path", state_dir / "webui.db")
    monkeypatch.setattr(_ws.drafts_store, "path", state_dir / "webui.db")
    monkeypatch.setattr(_ws.schedule_store, "path", state_dir / "webui.db")



# ═════════════════════════════════════════════════════════════════════════════
def test_every_route_has_at_least_one_contract_test():
    """Enumerate routes in webui.app + assert each is exercised by a real
    client.get / client.post call in this module.

    Two intentional design choices:

    1. Parametrized rules like '/sites/run/<run_id>/result' are translated to
       a regex where each '<param>' becomes a non-slash / non-quote run. This
       matches both literal forms (``client.get("/sites/run/abc/result")``)
       and f-string forms (``client.get(f"/sites/run/{run_id}/result")``).
    2. Coverage is matched against actual ``client.get(...)`` /
       ``client.post(...)`` calls — not raw string presence. A route that
       appears only in a docstring, comment, or assertion message MUST NOT
       count as covered, otherwise the gate gives a false sense of safety.
    """
    import webui

    rules = {r.rule for r in webui.app.url_map.iter_rules() if r.endpoint != "static"}

    # Scan all test_webui_*.py files for route coverage
    import glob
    test_dir = Path(__file__).parent
    this_file = "\n".join(
        open(f, encoding="utf-8").read()
        for f in sorted(glob.glob(str(test_dir / "test_webui_*.py")))
    )

    uncovered = []
    for rule in sorted(rules):
        # Translate Flask path params to a permissive segment regex; escape
        # the literal segments so special chars (e.g. ':' in '/ce:plan')
        # cannot become regex metacharacters.
        parts = re.split(r"(<[^>]+>)", rule)
        rule_pattern = "".join(
            r"[^/\"']+" if p.startswith("<") else re.escape(p)
            for p in parts
        )
        # Require a real client.{get,post}(...) invocation. The closing char
        # is a quote (rule ends there) or '?' (query string immediately
        # follows the path, e.g. '?error=access_denied').
        call_re = re.compile(
            rf"client\.(?:get|post)\(\s*f?[\"']{rule_pattern}[\"'?]"
        )
        if not call_re.search(this_file):
            uncovered.append(rule)

    assert not uncovered, (
        f"Routes without contract test coverage: {uncovered}. "
        f"Plan 2026-05-18-001 Unit 1 requires every route to have ≥1 test "
        f"that invokes client.get/post on the route."
    )



class TestGetRoutes:
    def test_root_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_homepage_has_mode_toggle(self, client):
        """Plan 012 Unit 5 — single/batch toggle DOM present on home page."""
        resp = client.get("/")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8", errors="ignore")
        assert 'id="modeToggleBar"' in body
        assert 'id="mode-single-btn"' in body
        assert 'id="mode-batch-btn"' in body
        assert 'data-bs-target="#newPanel"' in body
        assert 'data-bs-target="#batchPanel"' in body

    def test_homepage_loads_mode_toggle_script(self, client):
        """Plan 012 Unit 5 — mode toggle is wired up. Plan 007 U6: mode_toggle.js
        is now imported by the index.js ES module (no separate <script> tag)."""
        resp = client.get("/")
        body = resp.data.decode("utf-8", errors="ignore")
        assert "js/index.js" in body and 'type="module"' in body
        # Server-side hint must be injected so the JS can read batch_tab flag
        # without an extra round-trip.
        assert "window.__batchTabHint" in body

    def test_nav_tabs_reduced_to_two(self, client):
        """Plan 012 Unit 6 — batch-tab nav button removed; nav now has 2 tabs."""
        resp = client.get("/")
        body = resp.data.decode("utf-8", errors="ignore")
        assert 'id="batch-tab"' not in body
        assert 'id="new-tab"' in body
        assert 'id="history-tab"' in body

    def test_batch_panel_still_renders_for_toggle_access(self, client):
        """Plan 012 Unit 6 — #batchPanel tab-pane DOM stays (toggle activates it)."""
        resp = client.get("/")
        body = resp.data.decode("utf-8", errors="ignore")
        assert 'id="batchPanel"' in body
        assert 'action="/ce:batch"' in body

    def test_mode_toggle_js_file_exists(self):
        """Plan 012 Unit 5 — the new static JS asset is present on disk."""
        from pathlib import Path
        js = (
            Path(__file__).resolve().parents[1]
            / "webui_app" / "static" / "js" / "mode_toggle.js"
        )
        assert js.exists(), f"mode_toggle.js missing at {js}"
        contents = js.read_text(encoding="utf-8")
        assert "webui_mode_default" in contents
        assert "__batchTabHint" in contents

    def test_mode_toggle_js_u1_behaviors(self):
        """Plan 013 U1 — mode_toggle.js contains all 4 new polish behaviors."""
        from pathlib import Path
        js_path = (
            Path(__file__).resolve().parents[1]
            / "webui_app" / "static" / "js" / "mode_toggle.js"
        )
        contents = js_path.read_text(encoding="utf-8")

        # Behavior 1: URL stash key present
        assert "webui_url_stash" in contents, "URL stash key missing"

        # Behavior 2: Mid-pipeline confirm uses _plansData
        assert "_plansData" in contents, "mid-pipeline confirm missing"
        assert "confirm(" in contents, "confirm dialog missing"

        # Behavior 3: ?tab=batch deep-link via URLSearchParams
        assert "URLSearchParams" in contents, "URLSearchParams deep-link missing"
        assert "tab" in contents, "tab param check missing"

        # Behavior 4: body class toggle for CSS scoping
        assert "mode-single" in contents, "mode-single body class missing"
        assert "mode-batch" in contents, "mode-batch body class missing"
        assert "applyBodyModeClass" in contents, "applyBodyModeClass helper missing"

    def test_mode_toggle_tab_deep_link_route_accessible(self, client):
        """Plan 013 U1 — GET /?tab=batch returns 200 (server-side hint injected)."""
        resp = client.get("/?tab=batch")
        assert resp.status_code == 200
        body = resp.data.decode("utf-8", errors="ignore")
        # The page still renders; JS handles the deep-link client-side
        assert "batchPanel" in body

    def test_sticky_step_bar_css_scoped_to_single_mode(self, client):
        """Plan 013 U3 — step-bar sticky rule scoped to body.mode-single only."""
        resp = client.get("/")
        body = resp.data.decode("utf-8", errors="ignore")
        # Scoped sticky rules must appear in the inlined CSS
        assert "mode-single" in body, "mode-single CSS scope missing from rendered page"
        assert "step-bar" in body, "step-bar CSS missing from rendered page"
        assert "mode-batch" in body, "mode-batch CSS scope missing"

    def test_sticky_step_bar_css_in_template_source(self):
        """Plan 013 U3 — scoped step-bar rules present in extracted CSS file (Plan B Unit 1)."""
        from pathlib import Path
        # CSS extracted to static file by Plan B Unit 1; check index.css not index.html
        src = (
            Path(__file__).resolve().parents[1]
            / "webui_app" / "static" / "css" / "index.css"
        ).read_text(encoding="utf-8")
        # Both mode-scoped rules must be present
        assert "body.mode-single .step-bar" in src, (
            "mode-single step-bar sticky rule missing from index.css"
        )
        assert "body.mode-batch .step-bar" in src, (
            "mode-batch step-bar static rule missing from index.css"
        )
        assert "hide-history-nav" in src, (
            "hide-history-nav CSS rule missing from index.css"
        )

    def test_root_does_not_crash_with_missing_state_files(self, client, tmp_path):
        """Edge case: first-time startup with no persisted state. history_store
        is still JSON-backed so its file is genuinely absent; the SQLite-backed
        stores (now sharing webui.db) start empty. Index must still render."""
        import webui_store as ws

        assert not ws.history_store.path.exists()
        # drafts_store is SQLite-backed now: the db file may be created eagerly
        # by the path redirect, but it must start empty.
        assert ws.drafts_store.load() == []

        resp = client.get("/")
        assert resp.status_code == 200

    # test_settings_returns_200, test_settings_with_flash_query_renders,
    # test_settings_html_contract, test_blogger_forms_scoped_to_channel_panel,
    # test_medium_forms_scoped_to_channel_panel removed — legacy /settings page
    # retired in U8 (Plan 2026-06-18-002). SPA at /app/settings replaces it.

    def test_sites_returns_200(self, client):
        resp = client.get("/sites")
        assert resp.status_code == 200

    def test_sites_with_saved_query_renders(self, client):
        resp = client.get("/sites?saved=https://x.com&autofilled=list_url")
        assert resp.status_code == 200

    def test_ce_history_get_returns_200(self, client):
        resp = client.get("/ce:history")
        assert resp.status_code == 200

    def test_sites_scrape_preview_missing_url_returns_400(self, client):
        resp = client.get("/sites/scrape-preview")
        assert resp.status_code == 400

    def test_sites_scrape_preview_with_url_returns_200_json(
        self, client, monkeypatch,
    ):
        # Avoid real HTTP scraping
        monkeypatch.setattr("webui.fetch_work_metadata", lambda url: None)
        resp = client.get("/sites/scrape-preview?url=https://x.com/work/1")
        assert resp.status_code == 200
        assert resp.headers["Content-Type"].startswith("application/json")

    def test_sites_run_result_redirects_to_keep_alive(self, client):
        # U8/R2: /sites/run/<id>/result is collapsed into the keep-alive flow
        # (the in-memory result page is gone) — it now always 302-redirects.
        resp = client.get("/sites/run/00000000T000000-aaaaaaaa/result")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/ce:keep-alive")

    def test_blogger_oauth_callback_missing_state_redirects(self, client):
        resp = client.get("/settings/blogger/oauth-callback")
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/app/settings?")


# ═════════════════════════════════════════════════════════════════════════════
# Pipeline POST routes — /ce:*
# ═════════════════════════════════════════════════════════════════════════════



class TestCsrfGuard:
    """Lock in that ``_global_csrf_guard`` rejects state-mutating verbs
    without a valid token. The class above's ``client`` fixture disables
    CSRF via TESTING/WTF_CSRF_ENABLED; this test builds its own app so
    the production hook path is exercised."""

    def test_post_without_csrf_token_returns_403(self):
        from webui_app import create_app
        a = create_app(start_scheduler=False)
        with a.test_client() as c:
            resp = c.post('/settings/save-llm-config', data={'endpoint': 'x'})
            assert resp.status_code == 403, (
                f"Expected 403 from global CSRF guard, got {resp.status_code}. "
                "Regression of _global_csrf_guard in webui_app/__init__.py."
            )



class TestSecretLeakRegression:
    """Guard against the P3 pattern reappearing — long-term credentials must
    never be re-rendered into HTML where DevTools can read them."""

    def test_llm_settings_loose_perms_fixed_on_load(self, client):
        """O8: pre-#140 llm-settings.json files written at 0o644 must be
        auto-tightened to 0o600 when the read path loads them.

        The write path routes through ``atomic_write`` (0o600), but a file
        created by pre-#140 code stays world-readable until re-saved. The
        loader mirrors ``_util/secrets.py``'s frw-token reader: warn + chmod.
        """
        import json as _json
        import os as _os
        import stat as _stat
        from webui_app.helpers.contexts import (
            _llm_settings_file,
            _load_llm_settings,
        )

        path = _llm_settings_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Simulate a pre-#140 hand-rolled write: real file, loose 0o644 perms.
        path.write_text(_json.dumps({"api_key": "sk-legacy-0644"}),
                        encoding="utf-8")
        _os.chmod(path, 0o644)
        assert _stat.S_IMODE(path.stat().st_mode) == 0o644

        settings = _load_llm_settings()
        # Behaviour otherwise identical: the api_key still loads.
        assert settings["api_key"] == "sk-legacy-0644"
        # ...but the file is now 0o600.
        mode = _stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600, (
            f"llm-settings.json mode is {oct(mode)} — loader must auto-chmod "
            "a pre-existing 0o644 file to 0o600 (O8)."
        )

    # test_blogger_client_secret_not_rendered removed — legacy /settings Jinja
    # page retired in U8 (Plan 2026-06-18-002); the template that could leak the
    # secret no longer exists.

    # test_llm_settings_file_is_0o600 removed — /settings/save-llm-config
    # deregistered in U8; 0o600 perm regression covered by test_webui_api_v1_llm.py.

    # test_test_llm_generation_returns_json, test_test_image_gen_returns_json,
    # test_generate_sample_image_returns_json removed — legacy /settings/test-*
    # routes deregistered in U8; covered by test_webui_api_v1_llm_diagnostics.py
    # and test_webui_api_v1_image_gen.py.



