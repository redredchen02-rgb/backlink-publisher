"""Plan 2026-07-06-004 Unit 5 — checkpoint.py / drafts.py flash-redirect
sanitization migration.

Both route modules used to splice ``flash_type``/``flash_msg`` directly into
an f-string / literal ``redirect(...)`` call, bypassing the centralised
``_safe_flash_redirect`` sanitizer (CR/LF strip, length cap, URL-quote) that
every other redirect-producing route already uses (oauth.py,
settings_basic.py, llm.py, main.py). This covers:

  * checkpoint.py's 2 call sites now call ``_safe_flash_redirect`` directly.
  * drafts.py's 8 call sites now go through the local ``_draft_redirect``
    helper, which calls ``_safe_flash_redirect`` and prepends a static
    ``tab=draft`` onto the already-sanitized Location header (kept for
    backward compat with main.py's ``/jinja`` fallback and the existing
    test suite — see drafts.py's ``_draft_redirect`` docstring) without
    producing an invalid double-``?`` URL.

Uses the shared ``client`` fixture from tests/conftest.py (CSRF disabled,
``webui.app`` singleton) — the same fixture already used by
test_webui_checkpoint.py / test_drafts_bulk_routes.py / test_webui_history_routes.py.
"""
from __future__ import annotations

__tier__ = "unit"

from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlparse

import pytest

pytest.importorskip("flask")


def _location_query(resp) -> dict:
    """Parse the redirect Location header's query string into a dict of
    single (already-unquoted) values."""
    loc = resp.headers.get("Location", "")
    parsed = urlparse(loc)
    qs = parse_qs(parsed.query)
    return {k: v[0] for k, v in qs.items()}


# ── checkpoint.py ────────────────────────────────────────────────────────────


class TestCheckpointFlashRedirectSanitization:
    _VALID_RUN_ID = "20260528T120000-deadbeef"

    def test_dismiss_success_uses_safe_flash_redirect_path(self, client):
        """Success path: Location is bare '/' + sanitized/quoted query params
        (no tab=draft — checkpoint.py has no draft-tab concept)."""
        with patch("backlink_publisher.checkpoint.delete", return_value=None):
            resp = client.post(
                "/checkpoint/dismiss", data={"run_id": self._VALID_RUN_ID},
            )
        assert resp.status_code == 302
        loc = resp.headers["Location"]
        assert loc.startswith("/?")
        q = _location_query(resp)
        assert q["flash_type"] == "success"
        assert q["flash_msg"] == "检查点已删除"

    def test_dismiss_failure_uses_safe_flash_redirect_path(self, client):
        with patch("backlink_publisher.checkpoint.delete",
                   side_effect=PermissionError("locked")):
            resp = client.post(
                "/checkpoint/dismiss", data={"run_id": self._VALID_RUN_ID},
            )
        assert resp.status_code == 302
        q = _location_query(resp)
        assert q["flash_type"] == "danger"
        assert q["flash_msg"] == "删除检查点失败，该检查点仍然存在"

    def test_dismiss_flash_msg_is_url_quoted_not_raw(self, client):
        """Sanity check that the message is actually run through the
        sanitizer's quote() call rather than spliced in raw — the raw Chinese
        text must not appear un-encoded in the Location header."""
        with patch("backlink_publisher.checkpoint.delete", return_value=None):
            resp = client.post(
                "/checkpoint/dismiss", data={"run_id": self._VALID_RUN_ID},
            )
        loc = resp.headers["Location"]
        assert "检查点已删除" not in loc
        assert unquote(loc) != loc


# ── drafts.py ────────────────────────────────────────────────────────────────


class TestDraftFlashRedirectSanitization:
    def test_save_redirect_preserves_tab_draft_and_sanitizes(self, client):
        """tab=draft is still emitted (backward compat), followed by the
        sanitized flash_type/flash_msg — no double '?'."""
        resp = client.post("/ce:draft/save", data={"plans": ""})
        assert resp.status_code == 302
        loc = resp.headers["Location"]
        assert loc.startswith("/?tab=draft&")
        assert "??" not in loc
        assert loc.count("?") == 1
        q = _location_query(resp)
        assert q["tab"] == "draft"
        assert "flash_type" in q
        assert "flash_msg" in q

    def test_flash_msg_with_ampersand_hash_and_newline_survives_intact(self, client):
        """A flash_msg containing '&', '#', and a newline must not break the
        URL and must arrive intact (modulo CR/LF stripping) on the other end."""
        from webui_app.routes import drafts as drafts_mod
        dirty_msg = "已保存 & 完成\n第二行 # 标签"
        fake_result = {"ok": True, "flash_type": "success", "flash_msg": dirty_msg}
        with patch.object(drafts_mod._draft, "create", return_value=fake_result):
            resp = client.post("/ce:draft/save", data={"plans": '{"id": "x"}'})
        assert resp.status_code == 302
        loc = resp.headers["Location"]
        assert loc.count("?") == 1
        q = _location_query(resp)
        assert q["tab"] == "draft"
        assert q["flash_type"] == "success"
        # CR/LF collapsed to a space by the sanitizer; '&'/'#' preserved as
        # literal characters once decoded (they were quoted for transit).
        assert "已保存 & 完成" in q["flash_msg"]
        assert "第二行 # 标签" in q["flash_msg"]
        assert "\n" not in q["flash_msg"]

    def test_flash_msg_is_length_capped(self, client):
        from webui_app.routes import drafts as drafts_mod
        long_msg = "危" * 500
        fake_result = {"ok": True, "flash_type": "success", "flash_msg": long_msg}
        with patch.object(drafts_mod._draft, "create", return_value=fake_result):
            resp = client.post("/ce:draft/save", data={"plans": '{"id": "x"}'})
        q = _location_query(resp)
        assert len(q["flash_msg"]) <= 200

    @pytest.mark.parametrize(
        "path,form",
        [
            ("/ce:draft/schedule", {}),
            ("/ce:draft/publish-now", {}),
            ("/ce:draft/cancel", {}),
            ("/ce:draft/delete", {}),
            ("/ce:draft/bulk-delete", {}),
            ("/ce:draft/bulk-publish-now", {}),
            ("/ce:draft/bulk-cancel", {}),
        ],
    )
    def test_all_draft_routes_emit_single_question_mark(self, client, path, form):
        """Every one of the 8 migrated call sites must produce a well-formed
        single-'?' URL (no double-'?' regression)."""
        resp = client.post(path, data=form)
        assert resp.status_code == 302
        loc = resp.headers["Location"]
        assert loc.count("?") == 1
        assert loc.startswith("/?tab=draft")
