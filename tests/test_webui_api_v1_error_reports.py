"""Contract + security tests for ``/api/v1/error-reports`` (Plan
2026-07-01-002 Unit 3).

Covers: sanitize-before-persist, the fingerprint merge (open vs. already-
resolved vs. manual-exempt), CSRF enforcement, the request-size guard, the
daily-cap gate (and its increment-exclusion), CRUD contract (POST/GET/PATCH/
DELETE), the failure-logging-never-leaks-secrets path, and the periodic
purge job.

Each test builds its own isolated ``BACKLINK_PUBLISHER_CONFIG_DIR`` (a fresh
``tmp_path``) and resets the ``error_report_store`` lazy singleton so rows
from one test never leak into another's count-based assertions (daily_cap,
purge).
"""

from __future__ import annotations

__tier__ = "integration"

from datetime import datetime, timedelta, UTC
import json as _json
from unittest.mock import MagicMock

import pytest

CSRF = "test-csrf-token"


# ── fixtures ─────────────────────────────────────────────────────────────────


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
    return client.post("/api/v1/error-reports", json=body, headers=headers, **kw)


def _patch(client, report_id, body):
    return client.patch(
        f"/api/v1/error-reports/{report_id}",
        json=body,
        headers={"X-CSRFToken": CSRF},
    )


def _delete(client, report_id):
    return client.delete(
        f"/api/v1/error-reports/{report_id}", headers={"X-CSRFToken": CSRF}
    )


def _auto_report(**overrides):
    """A payload shaped like an auto-captured error (carries reportId)."""
    base = {
        "reportId": "client-corr-1",
        "message": "TypeError: x is not a function",
        "stack": "at foo (app.js:1:1)",
        "url": "https://example.test/app/publish",
        "source": "vue",
        "severity": "error",
        "fingerprint": "fp-abc123",
    }
    base.update(overrides)
    return base


def _write_config(tmp_path, **error_reports_kwargs):
    lines = ["[error_reports]"]
    for k, v in error_reports_kwargs.items():
        lines.append(f'{k} = "{v}"' if isinstance(v, str) else f"{k} = {v}")
    (tmp_path / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


PROBLEM_CT = "application/problem+json"


# ── 1. Happy path: sanitize-before-persist ──────────────────────────────────


def test_post_persists_sanitized_not_raw(client):
    planted_secret = "Bearer sekrit-token-value-should-not-survive"
    resp = _post(client, _auto_report(message=f"boom leaked {planted_secret}"))
    assert resp.status_code == 201
    report_id = resp.get_json()["id"]

    from webui_store.error_reports import error_report_store
    stored = error_report_store.get(report_id)
    assert stored is not None
    assert planted_secret not in _json.dumps(stored)
    # Paired positive: non-secret fields survive untouched.
    assert stored["source"] == "vue"
    assert stored["severity"] == "error"
    assert stored["status"] == "open"


# ── 2. Happy path: PATCH description doesn't disturb auto-captured fields ──


def test_patch_description_preserves_original_fields(client):
    resp = _post(client, _auto_report(message="original message", severity="error"))
    report_id = resp.get_json()["id"]

    patch_resp = _patch(client, report_id, {"description": "Happened after clicking Save"})
    assert patch_resp.status_code == 200
    body = patch_resp.get_json()
    assert body["user_description"] == "Happened after clicking Save"
    # Paired: original auto-captured fields are untouched.
    assert body["message"] == "original message"
    assert body["severity"] == "error"
    assert body["status"] == "open"


# ── 3. Edge case: CSRF paired (no token 403 / valid token 201) ─────────────


def test_post_without_csrf_token_is_403(app):
    c = app.test_client()  # deliberately no session csrf_token set
    resp = c.post("/api/v1/error-reports", json=_auto_report())
    assert resp.status_code == 403


def test_post_with_valid_csrf_token_succeeds(client):
    resp = _post(client, _auto_report())
    assert resp.status_code == 201


# ── 4. Edge case: daily_cap exceeded -> explicit ApiProblem, not a silent 200


def test_daily_cap_exceeded_returns_problem_and_saves_nothing(client, tmp_path):
    _write_config(tmp_path, daily_cap=1)

    r1 = _post(client, _auto_report(fingerprint="fp-cap-first", reportId="r1"))
    assert r1.status_code == 201

    r2 = _post(client, _auto_report(fingerprint="fp-cap-second", reportId="r2"))
    assert r2.status_code == 429
    assert r2.headers["Content-Type"].startswith(PROBLEM_CT)

    from webui_store.error_reports import error_report_store
    assert len(error_report_store.list()) == 1  # nothing from r2 was saved


# ── 5. Error path: simulated store write failure -> RFC 9457, never 200 ────


def test_store_write_failure_returns_problem_not_200(client, monkeypatch):
    def _boom(self, report):
        raise RuntimeError("simulated disk failure")

    monkeypatch.setattr(
        "webui_store.error_reports.ErrorReportSqliteStore.add", _boom
    )

    resp = _post(client, {"message": "harmless", "source": "manual"})
    assert resp.status_code == 502
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
    assert "Traceback" not in resp.get_data(as_text=True)


# ── 6. Error path: failure logging never leaks a planted secret ───────────


def test_persist_failure_logging_never_leaks_secret(client, monkeypatch):
    import webui_app.api.v1.error_reports as er_mod

    fake_logger = MagicMock()
    monkeypatch.setattr(er_mod, "plan_logger", fake_logger)

    secret = "sk-FAKE-PLANTED-SECRET-1234567890"

    def _boom(self, report):
        raise RuntimeError(f"disk write failed while storing near {secret}")

    monkeypatch.setattr(
        "webui_store.error_reports.ErrorReportSqliteStore.add", _boom
    )

    resp = _post(client, {"message": "harmless", "source": "manual",
                          "user_description": secret})
    assert resp.status_code == 502
    assert secret not in resp.get_data(as_text=True)

    assert fake_logger.error.called
    for call in fake_logger.error.call_args_list:
        for arg in list(call.args) + list(call.kwargs.values()):
            assert secret not in str(arg)


# ── 7. Integration: POST then GET list sees it (real wiring, not mocks) ───


def test_posted_report_appears_in_get_list(client):
    resp = _post(client, _auto_report(fingerprint="fp-list-check"))
    report_id = resp.get_json()["id"]

    list_resp = client.get("/api/v1/error-reports")
    assert list_resp.status_code == 200
    ids = [item["id"] for item in list_resp.get_json()["items"]]
    assert report_id in ids


# ── 8. Edge case: oversized body rejected before parsing/sanitization ──────


def test_oversized_body_rejected_before_parsing(client, monkeypatch):
    import webui_app.api.v1.error_reports as er_mod

    fake_sanitize = MagicMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(er_mod, "sanitize_error_report", fake_sanitize)

    huge = {"message": "x" * 200_000}
    resp = _post(client, huge)

    assert resp.status_code == 413
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)
    fake_sanitize.assert_not_called()

    from webui_store.error_reports import error_report_store
    assert error_report_store.list() == []


# ── 9. Happy path: same fingerprint increments; different fingerprint adds ─


def test_same_fingerprint_increments_existing_open_report(client):
    r1 = _post(client, _auto_report(fingerprint="fp-dup", reportId="corr-1"))
    assert r1.status_code == 201
    id1 = r1.get_json()["id"]

    r2 = _post(client, _auto_report(fingerprint="fp-dup", reportId="corr-2",
                                    message="same bug again"))
    assert r2.status_code == 200
    body2 = r2.get_json()
    assert body2["id"] == id1
    assert body2["occurrences"] == 2

    list_resp = client.get("/api/v1/error-reports")
    ids = [item["id"] for item in list_resp.get_json()["items"]]
    assert ids.count(id1) == 1  # still only one row for this fingerprint


def test_different_fingerprint_adds_new_row(client):
    r1 = _post(client, _auto_report(fingerprint="fp-a", reportId="corr-a"))
    r2 = _post(client, _auto_report(fingerprint="fp-b", reportId="corr-b"))
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.get_json()["id"] != r2.get_json()["id"]


# ── 10. Resolved-recurrence nuance: add() a fresh row, not increment ───────


def test_recurrence_after_resolved_creates_new_row_not_increment(client):
    r1 = _post(client, _auto_report(fingerprint="fp-recur", reportId="r1"))
    assert r1.status_code == 201
    first_id = r1.get_json()["id"]

    patch_resp = _patch(client, first_id, {"status": "resolved"})
    assert patch_resp.status_code == 200
    assert patch_resp.get_json()["status"] == "resolved"

    r2 = _post(client, _auto_report(fingerprint="fp-recur", reportId="r2"))
    assert r2.status_code == 201
    second_id = r2.get_json()["id"]
    assert second_id != first_id

    from webui_store.error_reports import error_report_store
    assert error_report_store.get(first_id)["occurrences"] == 1
    assert error_report_store.get(first_id)["status"] == "resolved"
    assert error_report_store.get(second_id)["occurrences"] == 1
    assert error_report_store.get(second_id)["status"] == "open"


# ── 11. daily_cap excludes increments, counts distinct new fingerprints ────


def test_daily_cap_excludes_increments_but_counts_new_fingerprints(client, tmp_path):
    _write_config(tmp_path, daily_cap=1)

    r1 = _post(client, _auto_report(fingerprint="fp-cap-a", reportId="corr-a"))
    assert r1.status_code == 201

    # Repeated increments on the SAME fingerprint must not count against the cap.
    for _ in range(5):
        r = _post(client, _auto_report(fingerprint="fp-cap-a", reportId="corr-a"))
        assert r.status_code == 200

    # A distinct new fingerprint is the 2nd genuinely-new row -> cap (1) is hit.
    r2 = _post(client, _auto_report(fingerprint="fp-cap-b", reportId="corr-b"))
    assert r2.status_code == 429
    assert r2.headers["Content-Type"].startswith(PROBLEM_CT)


# ── 12. DELETE existing -> 200 + subsequent GET 404; DELETE missing -> 404 ─


def test_delete_existing_then_get_returns_404(client):
    resp = _post(client, _auto_report(fingerprint="fp-del"))
    report_id = resp.get_json()["id"]

    del_resp = _delete(client, report_id)
    assert del_resp.status_code == 200
    assert del_resp.get_json()["ok"] is True

    get_resp = client.get(f"/api/v1/error-reports/{report_id}")
    assert get_resp.status_code == 404
    assert get_resp.headers["Content-Type"].startswith(PROBLEM_CT)


def test_delete_nonexistent_id_returns_404(client):
    resp = _delete(client, "no-such-id")
    assert resp.status_code == 404
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)


# ── 13. Integration: purge job removes expired, keeps fresh ────────────────


def test_purge_job_removes_expired_keeps_fresh(app, tmp_path):
    _write_config(tmp_path, retention_days=7)

    from webui_store.error_reports import error_report_store
    real_store = error_report_store._real()

    fresh_id = error_report_store.add(_auto_report(fingerprint="fp-fresh"))
    old_id = error_report_store.add(_auto_report(fingerprint="fp-old"))

    old_ts = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    with real_store._db.connect() as conn:
        conn.execute(
            "UPDATE error_reports SET created_at = ? WHERE id = ?",
            (old_ts, old_id),
        )

    from webui_app.api.v1.error_reports import purge_expired_error_reports
    removed = purge_expired_error_reports()

    assert removed == 1
    assert error_report_store.get(old_id) is None
    assert error_report_store.get(fresh_id) is not None


# ── 14. Manual report exemption from fingerprint dedup ─────────────────────


def test_manual_report_always_adds_even_with_matching_fingerprint(client):
    r1 = _post(client, _auto_report(fingerprint="fp-shared", reportId="corr-1"))
    assert r1.status_code == 201
    id1 = r1.get_json()["id"]

    manual_payload = {
        "message": "I clicked publish and nothing happened",
        "source": "manual",
        "fingerprint": "fp-shared",  # deliberately matches -- must NOT merge
    }
    r2 = _post(client, manual_payload)  # no reportId
    assert r2.status_code == 201
    id2 = r2.get_json()["id"]
    assert id2 != id1

    from webui_store.error_reports import error_report_store
    assert error_report_store.get(id1)["occurrences"] == 1  # unaffected


def test_manual_report_happy_path_no_fingerprint_at_all(client):
    resp = _post(client, {"message": "Publish button did nothing", "source": "manual"})
    assert resp.status_code == 201
    assert "id" in resp.get_json()


# ── Extra coverage: gaps in the plan's own scenario list ────────────────────


def test_patch_invalid_status_returns_400(client):
    """Approach step 4 requires this; not in the plan's enumerated scenarios."""
    resp = _post(client, _auto_report(fingerprint="fp-badstatus"))
    report_id = resp.get_json()["id"]

    patch_resp = _patch(client, report_id, {"status": "not-a-real-status"})
    assert patch_resp.status_code == 400
    assert patch_resp.headers["Content-Type"].startswith(PROBLEM_CT)

    # Paired: the status must not have silently changed.
    from webui_store.error_reports import error_report_store
    assert error_report_store.get(report_id)["status"] == "open"


def test_patch_nonexistent_id_returns_404(client):
    resp = _patch(client, "no-such-id", {"status": "acknowledged"})
    assert resp.status_code == 404
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)


def test_get_single_report_happy_path(client):
    resp = _post(client, _auto_report(fingerprint="fp-detail"))
    report_id = resp.get_json()["id"]

    get_resp = client.get(f"/api/v1/error-reports/{report_id}")
    assert get_resp.status_code == 200
    assert get_resp.get_json()["id"] == report_id


def test_get_single_report_nonexistent_returns_404(client):
    resp = client.get("/api/v1/error-reports/no-such-id")
    assert resp.status_code == 404
    assert resp.headers["Content-Type"].startswith(PROBLEM_CT)


def test_get_list_filters_by_status_paired(client):
    r1 = _post(client, _auto_report(fingerprint="fp-open-x"))
    r2 = _post(client, _auto_report(fingerprint="fp-resolved-x"))
    id1, id2 = r1.get_json()["id"], r2.get_json()["id"]
    _patch(client, id2, {"status": "resolved"})

    resolved_resp = client.get("/api/v1/error-reports?status=resolved")
    resolved_ids = {item["id"] for item in resolved_resp.get_json()["items"]}
    assert id2 in resolved_ids       # positive
    assert id1 not in resolved_ids  # negative, paired with the positive
