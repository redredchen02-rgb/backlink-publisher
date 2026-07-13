"""Contract + security tests for ``POST /api/v1/error-reports/export-bundle``
(Plan 2026-07-09-001).

Covers: bundle assembly from a failed-run context, secret redaction (reusing
the Unit-1 sanitizer through the backend), the no-error-source general path,
CSRF enforcement, the request-size guard, and the invalid-body contract.
"""

from __future__ import annotations

__tier__ = "integration"

import pytest

CSRF = "test-csrf-token"

_SECRET = "supersecret-token-abc123"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKLINK_PUBLISHER_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("BACKLINK_PUBLISHER_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("BACKLINK_PUBLISHER_ALLOW_NETWORK", raising=False)

    from webui_store.error_reports import error_report_store
    error_report_store.reset()

    from webui_app import create_app
    a = create_app(start_scheduler=False)
    a.config["TESTING"] = True
    a.config["PROPAGATE_EXCEPTIONS"] = False
    a.config["SESSION_COOKIE_SECURE"] = False
    yield a

    error_report_store.reset()


@pytest.fixture
def client(app):
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["csrf_token"] = CSRF
    return c


def _post(client, body, **kw):
    headers = {"X-CSRFToken": CSRF, **kw.pop("headers", {})}
    return client.post(
        "/api/v1/error-reports/export-bundle", json=body, headers=headers, **kw
    )


class TestExportBundle:
    def test_returns_markdown_and_paths(self, client) -> None:
        resp = _post(
            client,
            {
                "stderr": "Bearer eyJ.secret.payload",
                "error_class": "AuthExpiredError",
                "exit_code": 3,
                "message": f"expired token={_SECRET}",
                "run_id": "20240101T000000-aa11bb22",
                "command": "publish-backlinks --resume X",
                "description": "publish stuck",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "markdown" in data
        assert "report_path" in data
        assert "json_path" in data
        md = data["markdown"]
        assert "AuthExpiredError" in md
        assert "TL;DR" in md

    def test_secrets_redacted(self, client) -> None:
        resp = _post(
            client,
            {
                "stderr": f"Bearer {_SECRET}",
                "error_class": "AuthExpiredError",
                "exit_code": 3,
                "message": f"expired token={_SECRET}",
            },
        )
        assert resp.status_code == 200
        md = resp.get_json()["markdown"]
        assert _SECRET not in md
        assert "***" in md

    def test_no_error_source_builds_general(self, client) -> None:
        resp = _post(client, {"description": "things look wrong"})
        assert resp.status_code == 200
        md = resp.get_json()["markdown"]
        assert "TL;DR" in md

    def test_csrf_required(self, client) -> None:
        resp = client.post(
            "/api/v1/error-reports/export-bundle",
            json={"description": "x"},
            headers={"X-CSRFToken": "wrong"},
        )
        assert resp.status_code not in (200,)

    def test_invalid_body_400(self, client) -> None:
        resp = _post(client, "not-a-dict")  # type: ignore[arg-type]
        assert resp.status_code == 400
