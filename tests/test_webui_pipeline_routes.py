"""WebUI route contract tests — pipeline routes."""

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
        ("webui_app.helpers.cli_runner.run_pipe", _fake),
        ("webui_app.api.pipeline_api.run_pipe", _fake),
        ("webui_app.api.pipeline_api.run_pipe_capture", _fake_capture),
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
def _loopback_origin(client):
    """Send a loopback Origin on every request.

    The /ce:batch + /ce:publish-real blueprint added an Origin guard
    (``_check_bind_origin_or_abort``, commit fb0b82e) that 403s a POST with no
    Origin/Referer. A real browser always sends Origin; the bare test client did
    not, so these route tests began 403ing. Set an allowlisted loopback Origin
    matching the guard's expected host/port for the whole module.
    """
    from webui_app.helpers.security import _FLASK_PORT

    client.environ_base["HTTP_ORIGIN"] = f"http://127.0.0.1:{_FLASK_PORT}"


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

class TestPipelineRoutes:
    def test_ce_clear_returns_200(self, client):
        resp = client.post("/ce:clear")
        assert resp.status_code == 200

    def test_ce_plan_with_main_url_returns_200(self, client):
        resp = client.post("/ce:plan", data={"main_url": "https://example.com/"})
        assert resp.status_code == 200

    def test_ce_plan_missing_main_url_returns_200_with_error(self, client):
        """Empty submit re-renders index with error (not 400/422)."""
        resp = client.post("/ce:plan", data={})
        assert resp.status_code == 200

    def test_ce_plan_non_https_main_url_returns_200_with_error(self, client):
        """http:// triggers field error; renders index, not 4xx."""
        resp = client.post("/ce:plan", data={"main_url": "http://insecure.example/"})
        assert resp.status_code == 200

    def test_ce_plan_ignores_derive_source_extra_field(self, client):
        """Plan 2026-05-20-002 R7 invariant: the nameless ``derive_source``
        input is the new paste-to-derive entry on the homepage; browsers
        never submit nameless inputs. If a malicious client smuggles it
        anyway, the extras-loop (``key.startswith('url_')``) must NOT
        capture it (``derive_source`` doesn't match ``url_*``). The
        backend treats it as an unknown form key and ignores it; the
        ``main_url`` happy path is unaffected.
        """
        resp = client.post(
            "/ce:plan",
            data={
                "main_url": "https://example.com/",
                "derive_source": "http://attacker.example/internal",
            },
        )
        assert resp.status_code == 200
        # The attacker URL must not appear in the rendered page (no leak
        # into derived form state / config preview / extras list).
        body = resp.get_data(as_text=True)
        assert "attacker.example" not in body

    def test_ce_generate_with_empty_session_returns_200(self, client):
        """No urls in session/form → error re-render, still 200."""
        resp = client.post("/ce:generate", data={})
        assert resp.status_code == 200

    def test_ce_generate_with_urls_returns_200(self, client):
        urls_json = json.dumps(["https://example.com/"])
        resp = client.post("/ce:generate", data={"urls_json": urls_json})
        assert resp.status_code == 200

    def test_ce_generate_corrupt_urls_json_surfaces_error(self, client):
        """Plan 009 Unit 4: non-empty malformed urls_json must surface an error
        and NOT silently generate against stale stored urls."""
        with client.session_transaction() as sess:
            sess["config"] = {"urls": ["https://stale-last-session.example/"]}
        with patch("webui_app.routes.pipeline.plan_logger.warn") as mock_warn:
            resp = client.post("/ce:generate",
                               data={"urls_json": "[not valid json"})
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "连结格式无效" in body
        assert "stale-last-session" not in body  # did not use stale urls
        # Prior tests may have polluted history_store with bad dates, causing
        # extra ``calc_next_available: bad date in history_store`` warn calls
        # during template rendering. Use assert_any_call instead of
        # assert_called_once to be resilient to this cross-test state leakage.
        mock_warn.assert_any_call("urls_json_parse_error", reason="JSONDecodeError")

    def test_ce_generate_default_urls_json_does_not_error(self, client):
        """Default '[]' is not 'corrupt' — must not trigger the parse error."""
        resp = client.post("/ce:generate", data={"urls_json": "[]"})
        assert resp.status_code == 200
        assert "连结格式无效" not in resp.data.decode()

    def test_ce_validate_with_no_plans_returns_200(self, client):
        resp = client.post("/ce:validate", data={})
        assert resp.status_code == 200

    def test_ce_validate_with_plans_returns_200(self, client):
        resp = client.post("/ce:validate", data={"plans": '{"id": "x"}'})
        assert resp.status_code == 200

    def test_ce_publish_with_no_data_returns_200(self, client):
        resp = client.post("/ce:publish", data={})
        assert resp.status_code == 200

    def test_ce_batch_with_no_urls_returns_200_with_error(self, client):
        resp = client.post("/ce:batch", data={"batch_urls": ""})
        assert resp.status_code == 200

    def test_ce_batch_with_urls_returns_200(self, client):
        resp = client.post(
            "/ce:batch",
            data={
                "batch_urls": "https://example.com/",
                "platform": "medium",
                "language": "zh-CN",
                "publish_mode": "draft",
            },
        )
        assert resp.status_code == 200

    def test_ce_batch_accepts_target_language(self, client):
        """Plan 013 U2 — batch route must accept `target_language` field."""
        resp = client.post(
            "/ce:batch",
            data={
                "batch_urls": "https://example.com/",
                "platform": "medium",
                "target_language": "zh-CN",
                "publish_mode": "draft",
            },
        )
        assert resp.status_code == 200

    def test_ce_batch_language_fallback_still_works(self, client):
        """Plan 013 U2 — legacy `language` field still accepted (backwards compat)."""
        resp = client.post(
            "/ce:batch",
            data={
                "batch_urls": "https://example.com/",
                "platform": "medium",
                "language": "en",
                "publish_mode": "draft",
            },
        )
        assert resp.status_code == 200

    def test_shared_config_selects_included_in_both_forms(self, client):
        """Plan 013 U2 — shared select partial used in both configForm and batchForm.

        The configForm is guarded by {% if config %} so it only renders when
        pipeline state is present.  We verify:
        - The batch form always renders target_language (always visible on GET /).
        - The index.html template source contains the include in both locations.
        - _shared_config_selects.html is present on disk.
        """
        from pathlib import Path

        # 1. Batch form always renders target_language
        resp = client.get("/")
        body = resp.data.decode("utf-8", errors="ignore")
        assert 'name="target_language"' in body, "batch form missing target_language"

        # 2. Template source uses the shared include in both form contexts.
        # Plan B Unit 2 moved the tab panes to _tab_*.html partials, so
        # _shared_config_selects.html now appears in _tab_new.html and
        # _tab_batch.html rather than index.html directly.
        templates_dir = Path(__file__).resolve().parents[1] / "webui_app" / "templates"
        all_template_src = "".join(
            p.read_text(encoding="utf-8")
            for p in templates_dir.glob("*.html")
        )
        count = all_template_src.count("_shared_config_selects.html")
        assert count == 2, (
            "expected 2 includes of _shared_config_selects.html across templates, got "
            + str(count)
        )

        # 3. The partial itself is on disk
        partial_path = (
            Path(__file__).resolve().parents[1]
            / "webui_app" / "templates" / "_shared_config_selects.html"
        )
        assert partial_path.exists(), "_shared_config_selects.html missing"
        partial_src = partial_path.read_text(encoding="utf-8")
        assert 'name="target_language"' in partial_src
        assert 'name="publish_mode"' in partial_src

    def test_ce_publish_real_with_no_data_returns_200(self, client):
        resp = client.post(
            "/ce:publish-real",
            data={"validated": "", "platform": "medium"},
        )
        assert resp.status_code == 200

    def test_ce_regen_body_missing_domain_returns_400(self, client):
        import json
        resp = client.post(
            "/ce:regen-body",
            data=json.dumps({"anchors": [], "language": "zh-CN"}),
            content_type="application/json",
        )
        assert resp.status_code == 400


# ═════════════════════════════════════════════════════════════════════════════
# History POST routes — /ce:history*
# ═════════════════════════════════════════════════════════════════════════════



class TestCheckpointRoutes:
    def test_resume_invalid_run_id_returns_400(self, client):
        resp = client.post("/checkpoint/resume", data={"run_id": "not-a-run-id"})
        assert resp.status_code == 400

    def test_resume_missing_run_id_returns_400(self, client):
        resp = client.post("/checkpoint/resume", data={})
        assert resp.status_code == 400

    def test_resume_valid_run_id_returns_200(self, client):
        # subprocess.run autouse-mocked → returns empty stdout success
        run_id = "20260518T000000-deadbeef"
        resp = client.post("/checkpoint/resume", data={"run_id": run_id})
        assert resp.status_code == 200

    def test_dismiss_invalid_run_id_returns_400(self, client):
        resp = client.post("/checkpoint/dismiss", data={"run_id": "bogus"})
        assert resp.status_code == 400

    def test_dismiss_valid_run_id_redirects_to_root(self, client):
        run_id = "20260518T000000-deadbeef"
        resp = client.post("/checkpoint/dismiss", data={"run_id": run_id})
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/?flash_type=success&flash_msg=")


# ═════════════════════════════════════════════════════════════════════════════
# Sites POST routes — /sites/save-three-url, /sites/run
# (GET /sites and GET /sites/scrape-preview / run/<id>/result covered above.)
# ═════════════════════════════════════════════════════════════════════════════



class TestPreviewRoutes:
    def test_ce_preview_returns_200(self, client):
        resp = client.post("/ce:preview", data={"urls_json": '["https://example.com"]'})
        assert resp.status_code == 200



class TestPipelinePublishChainRoute:
    def test_post_publish_chain_without_urls_returns_200(self, client):
        """POST /ce:publish-chain without valid URLs returns the page."""
        resp = client.post("/ce:publish-chain", data={})
        assert resp.status_code == 200

