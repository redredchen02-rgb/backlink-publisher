"""Unit 8: /sites/run POST and /sites/run/<id>/result GET redirect to keep-alive."""

import pytest

import webui


@pytest.fixture
def client(disable_csrf):
    return webui.app.test_client()


class TestSitesRunRedirect:
    """Both POST /sites/run and GET /sites/run/<id>/result should redirect
    to /ce:keep-alive — the pipeline is collapsed into the keep-alive flow."""

    def test_post_sites_run_redirects_to_keep_alive(self, client):
        """POST /sites/run → 302 to /ce:keep-alive."""
        resp = client.post("/sites/run", data={})
        assert resp.status_code == 302
        assert resp.location.endswith("/ce:keep-alive")

    def test_get_sites_run_result_redirects_to_keep_alive(self, client):
        """GET /sites/run/<id>/result → 302 to /ce:keep-alive."""
        resp = client.get("/sites/run/20260101T000000-abc123/result")
        assert resp.status_code == 302
        assert resp.location.endswith("/ce:keep-alive")
